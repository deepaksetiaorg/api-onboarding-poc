"""Turn the form answers into a codegen config, preview the class names, and run OpenAPI Generator.

Usage:
  python scripts/codegen.py config   -> work/codegen.yaml + work/preview.md
  python scripts/codegen.py run      -> work/output/ (runs openapi-generator-cli in Docker)

work/codegen.yaml is the same kind of config file teams used to write by hand. To plug this into an
existing pipeline instead, commit that file (or open a PR with it) and let your current workflow run.
"""
import os
import subprocess
import sys

import yaml

from common import WORK_DIR, load_form, pascal

GENERATOR_IMAGE = os.environ.get("GENERATOR_IMAGE", "openapitools/openapi-generator-cli:v7.10.0")
DEFAULT_ORG_PACKAGE = os.environ.get("DEFAULT_ORG_PACKAGE", "com.example")

# (language from form, server?) -> (generator name, extra additional-properties)
GENERATORS = {
    ("Java - Spring Boot", True): ("spring", {"useSpringBoot3": "true", "useTags": "true"}),
    ("Java - Spring Boot", False): ("java", {"library": "restclient"}),
    ("Java - plain client (OkHttp/Native)", True): ("java", {"library": "native"}),
    ("Java - plain client (OkHttp/Native)", False): ("java", {"library": "native"}),
    ("TypeScript - Axios", True): ("typescript-axios", {}),
    ("TypeScript - Axios", False): ("typescript-axios", {}),
    ("TypeScript - Angular", True): ("typescript-angular", {}),
    ("TypeScript - Angular", False): ("typescript-angular", {}),
    ("Python", True): ("python-fastapi", {}),
    ("Python", False): ("python", {}),
    ("C# / .NET", True): ("aspnetcore", {}),
    ("C# / .NET", False): ("csharp", {}),
}

OPT_VALIDATION = "Add validation annotations (e.g. @NotNull, @Size) based on spec rules"
OPT_INTERFACES = "Generate interfaces only (no default implementation)"
OPT_TESTS = "Include tests / test stubs"


def build_config(form: dict) -> dict:
    server = form.get("generation_type", "").startswith("Server")
    generator, extra = GENERATORS[(form["language"], server)]
    team_pkg = form.get("team_name", "").lower().replace("-", "").replace(" ", "")
    package = form.get("package_name") or f"{DEFAULT_ORG_PACKAGE}.{team_pkg}"
    options = form.get("options") or []

    props = dict(extra)
    if generator in ("spring", "java"):
        props.update({
            "groupId": form.get("group_id") or DEFAULT_ORG_PACKAGE,
            "artifactId": form.get("artifact_id") or form["api_name"],
            "basePackage": package,
            "apiPackage": f"{package}.api",
            "modelPackage": f"{package}.model",
            "invokerPackage": f"{package}.client",
            "configPackage": f"{package}.config",
            "useBeanValidation": str(OPT_VALIDATION in options).lower(),
        })
        if generator == "spring":
            props["interfaceOnly"] = str(OPT_INTERFACES in options).lower()
    elif generator.startswith("python"):
        props["packageName"] = package.replace(".", "_")
    elif generator in ("csharp", "aspnetcore"):
        props["packageName"] = ".".join(pascal(p) for p in package.split("."))
    elif generator.startswith("typescript"):
        props["npmName"] = f"@{team_pkg or 'org'}/{form['api_name']}"

    renames = {}
    for line in (form.get("class_renames") or "").splitlines():
        old, sep, new = line.partition(":")
        if sep:
            renames[old.strip()] = new.strip()

    return {
        "apiName": form["api_name"],
        "team": form.get("team_name"),
        "contact": form.get("contact"),
        "inputSpec": "work/spec.yaml",
        "generatorName": generator,
        "outputDir": "work/output",
        "modelNameSuffix": form.get("model_suffix") or "",
        "apiNameSuffix": form.get("api_suffix") or "",
        "modelNameMappings": renames,
        "additionalProperties": props,
        "skipTests": OPT_TESTS not in options,
    }


def preview(config: dict, spec: dict) -> str:
    """Predict the main class names so the team can sanity-check before downloading."""
    model_suffix = config["modelNameSuffix"]
    api_suffix = config["apiNameSuffix"] or "Api"
    renames = config["modelNameMappings"]

    models = []
    for name in (spec.get("components", {}) or {}).get("schemas", {}) or {}:
        final = renames.get(name) or f"{pascal(name)}{model_suffix}"
        models.append((name, final))

    tags = set()
    for path_item in (spec.get("paths") or {}).values():
        for op in (path_item or {}).values():
            if isinstance(op, dict):
                tags.update(op.get("tags") or ["default"])
    apis = sorted(f"{pascal(t)}{api_suffix}" for t in tags)

    props = config["additionalProperties"]
    lines = [
        "### What you'll get",
        f"- **Generator:** `{config['generatorName']}`",
    ]
    if "apiPackage" in props:
        lines += [f"- **API package:** `{props['apiPackage']}`", f"- **Model package:** `{props['modelPackage']}`"]
    if "artifactId" in props:
        lines.append(f"- **Maven coordinates:** `{props['groupId']}:{props['artifactId']}`")
    if "packageName" in props:
        lines.append(f"- **Package:** `{props['packageName']}`")
    lines += ["", "**API classes:** " + (", ".join(f"`{a}`" for a in apis) or "_none found_")]
    lines += ["", "| Schema in spec | Model class |", "|---|---|"]
    lines += [f"| `{old}` | `{new}` |" for old, new in models] or ["| _none_ | |"]
    if "default" in tags:
        lines += ["", "> Some operations have no tag, so they land in a `Default` API class. "
                      "Add `tags` to those operations in your spec for better names."]
    return "\n".join(lines)


def run(config: dict) -> None:
    os.makedirs(config["outputDir"], exist_ok=True)
    cmd = [
        "docker", "run", "--rm", "-u", f"{os.getuid()}:{os.getgid()}",
        "-v", f"{os.getcwd()}:/local", GENERATOR_IMAGE, "generate",
        "-i", f"/local/{config['inputSpec']}",
        "-g", config["generatorName"],
        "-o", f"/local/{config['outputDir']}",
    ]
    if config["modelNameSuffix"]:
        cmd += ["--model-name-suffix", config["modelNameSuffix"]]
    if config["apiNameSuffix"]:
        cmd += ["--api-name-suffix", config["apiNameSuffix"]]
    if config["modelNameMappings"]:
        cmd += ["--model-name-mappings", ",".join(f"{k}={v}" for k, v in config["modelNameMappings"].items())]
    if config["additionalProperties"]:
        cmd += ["--additional-properties",
                ",".join(f"{k}={v}" for k, v in config["additionalProperties"].items())]
    if config["skipTests"]:
        cmd += ["--global-property", "apiTests=false,modelTests=false"]
    print("Running:", " ".join(cmd))
    subprocess.run(cmd, check=True)


def main() -> None:
    action = sys.argv[1]
    config_path = os.path.join(WORK_DIR, "codegen.yaml")
    if action == "config":
        config = build_config(load_form())
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(config, f, sort_keys=False)
        with open(os.path.join(WORK_DIR, "spec.yaml"), encoding="utf-8") as f:
            spec = yaml.safe_load(f)
        with open(os.path.join(WORK_DIR, "preview.md"), "w", encoding="utf-8") as f:
            f.write(preview(config, spec))
        print(open(os.path.join(WORK_DIR, "preview.md"), encoding="utf-8").read())
    elif action == "run":
        with open(config_path, encoding="utf-8") as f:
            run(yaml.safe_load(f))
    else:
        sys.exit(f"unknown action {action}")


if __name__ == "__main__":
    main()
