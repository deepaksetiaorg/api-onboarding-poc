"""Parse and validate a submitted issue form.

Usage: python scripts/read_form.py <design|codegen|proxy>
Env:   ISSUE_BODY, ISSUE_NUMBER
Writes work/form.json (always) and work/errors.md (when invalid).
Outputs: valid=true|false, api_name, tracking_issue, ado_work_item
"""
import json
import os
import re
import sys

from common import WORK_DIR, parse_form, set_output

TEMPLATES = {
    "design": ".github/ISSUE_TEMPLATE/design-request.yml",
    "codegen": ".github/ISSUE_TEMPLATE/codegen-request.yml",
    "proxy": ".github/ISSUE_TEMPLATE/proxy-request.yml",
}

PACKAGE_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
CLASS_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def suggest_package(value: str) -> str:
    return re.sub(r"[^a-z0-9.]", "", value.lower().replace("-", "").replace(" ", ""))


def validate(step: str, form: dict) -> list[str]:
    errors = []
    api = form.get("api_name", "")
    if not SLUG_RE.match(api):
        errors.append(f"**API name** `{api}` should be lowercase letters, numbers and dashes, e.g. `member-api`.")
    if form.get("tracking_issue") and not form["tracking_issue"].lstrip("#").isdigit():
        errors.append("**Tracking issue number** was changed. Please use the link from your tracking issue.")
    if not form.get("spec_location"):
        errors.append("**OpenAPI spec location** is empty.")

    if step == "codegen":
        for field, label in (("package_name", "Base package name"), ("group_id", "Group ID")):
            value = form.get(field, "")
            if value and not PACKAGE_RE.match(value):
                errors.append(f"**{label}** `{value}` can only have lowercase letters, numbers and dots "
                              f"(no dashes or spaces). Try `{suggest_package(value)}`.")
        art = form.get("artifact_id", "")
        if art and not SLUG_RE.match(art):
            errors.append(f"**Artifact ID** `{art}` should be lowercase with dashes, e.g. `member-api`.")
        for field, label in (("model_suffix", "Model class suffix"), ("api_suffix", "API class suffix")):
            value = form.get(field, "")
            if value and not re.match(r"^[A-Z][A-Za-z0-9]*$", value):
                errors.append(f"**{label}** `{value}` should be one word starting with a capital letter, e.g. `Dto`.")
        for line in (form.get("class_renames") or "").splitlines():
            if not line.strip():
                continue
            old, sep, new = line.partition(":")
            if not sep or not CLASS_RE.match(old.strip()) or not CLASS_RE.match(new.strip()):
                errors.append(f"**Rename** line `{line.strip()}` should look like `SpecName: NewName`.")

    if step == "proxy":
        base = form.get("base_path", "")
        if base and not re.match(r"^/[A-Za-z0-9/_-]*$", base):
            errors.append(f"**Base path** `{base}` must start with `/` and use only letters, numbers, `-`, `_` and `/`.")
        target = form.get("target_url", "")
        if not target.startswith("https://"):
            errors.append(f"**Backend URL** `{target}` must start with `https://`.")
        rate = form.get("rate_limit", "")
        if rate and not re.match(r"^\d+(ps|pm)$", rate):
            errors.append(f"**Rate limit** `{rate}` should be a number followed by `ps` (per second) or `pm` (per minute), e.g. `20ps`.")
    return errors


def main() -> None:
    step = sys.argv[1]
    form = parse_form(os.environ.get("ISSUE_BODY", ""), TEMPLATES[step])
    form["step"] = step
    form["submission_issue"] = int(os.environ["ISSUE_NUMBER"]) if os.environ.get("ISSUE_NUMBER") else None
    form["tracking_issue"] = (form.get("tracking_issue") or "").lstrip("#")

    os.makedirs(WORK_DIR, exist_ok=True)
    with open(os.path.join(WORK_DIR, "form.json"), "w", encoding="utf-8") as f:
        json.dump(form, f, indent=2)

    errors = validate(step, form)
    if errors:
        with open(os.path.join(WORK_DIR, "errors.md"), "w", encoding="utf-8") as f:
            f.write("A few answers need a small fix before we can continue:\n\n")
            f.write("\n".join(f"- {e}" for e in errors))
            f.write("\n\nEdit this issue to fix them. The bot will run again automatically.\n")
        print("\n".join(errors))

    set_output("valid", "false" if errors else "true")
    set_output("api_name", form.get("api_name", ""))
    set_output("tracking_issue", form.get("tracking_issue", ""))
    set_output("ado_work_item", form.get("ado_work_item", ""))


if __name__ == "__main__":
    main()
