"""Fetch the spec named in work/form.json into work/spec.yaml and check it is OpenAPI 3.x.

Accepts: a path in this repo, a GitHub "blob" URL (any repo the token can read), or a raw https URL.
Env: SPEC_READ_TOKEN (optional, for specs in other private repos), GITHUB_TOKEN
Outputs: valid=true|false, spec_path
"""
import os
import re
import urllib.request

import yaml

from common import GITHUB_API, WORK_DIR, load_form, set_output

BLOB_RE = re.compile(r"^https://github\.com/([^/]+)/([^/]+)/blob/([^/]+)/(.+)$")


def download(location: str) -> str:
    token = os.environ.get("SPEC_READ_TOKEN") or os.environ.get("GITHUB_TOKEN", "")
    m = BLOB_RE.match(location)
    if m:
        owner, name, ref, path = m.groups()
        url = f"{GITHUB_API}/repos/{owner}/{name}/contents/{path}?ref={ref}"
        headers = {"Accept": "application/vnd.github.raw", "Authorization": f"Bearer {token}"}
    elif location.startswith("https://"):
        url, headers = location, {}
    else:
        path = os.path.normpath(location.lstrip("/"))
        if path.startswith(".."):
            raise ValueError("Spec path must be inside this repository.")
        with open(path, encoding="utf-8") as f:
            return f.read()
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers)) as resp:
        return resp.read().decode("utf-8")


def fail(message: str) -> None:
    with open(os.path.join(WORK_DIR, "errors.md"), "w", encoding="utf-8") as f:
        f.write(f"We couldn't use your spec: {message}\n\nEdit this issue to fix the spec location. The bot will run again.\n")
    print(message)
    set_output("valid", "false")


def main() -> None:
    location = load_form().get("spec_location", "").strip()
    try:
        text = download(location)
    except Exception as err:
        return fail(f"couldn't download `{location}` ({err}). Check the link, and that the file is in a repo we can read.")
    try:
        spec = yaml.safe_load(text)  # YAML loader also reads JSON
    except yaml.YAMLError as err:
        return fail(f"the file isn't valid YAML/JSON ({err}).")
    if not isinstance(spec, dict) or not str(spec.get("openapi", "")).startswith("3."):
        return fail("the file isn't an OpenAPI 3.x spec (the `openapi:` field should be `3.0.x` or `3.1.x`).")

    out = os.path.join(WORK_DIR, "spec.yaml")
    with open(out, "w", encoding="utf-8") as f:
        f.write(text)
    set_output("valid", "true")
    set_output("spec_path", out)


if __name__ == "__main__":
    main()
