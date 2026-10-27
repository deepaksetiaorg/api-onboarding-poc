"""Shared helpers: GitHub API, Azure DevOps API, issue-form parsing, workflow outputs.

Only uses the Python standard library + PyYAML, so workflows just need `pip install pyyaml`.
"""
import base64
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

import yaml

GITHUB_API = os.environ.get("GITHUB_API_URL", "https://api.github.com")
WORK_DIR = "work"
NO_RESPONSE = "_No response_"


# --------------------------------------------------------------------------- #
# GitHub
# --------------------------------------------------------------------------- #
def repo() -> str:
    return os.environ["GITHUB_REPOSITORY"]


def gh(method: str, path: str, data=None, token: str | None = None):
    """Call the GitHub REST API. `path` starts with '/'."""
    token = token or os.environ["GITHUB_TOKEN"]
    req = urllib.request.Request(
        GITHUB_API + path,
        method=method,
        data=json.dumps(data).encode() if data is not None else None,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            body = resp.read()
            return json.loads(body) if body else None
    except urllib.error.HTTPError as err:
        detail = err.read().decode(errors="replace")
        raise RuntimeError(f"GitHub API {method} {path} failed: {err.code} {detail}") from err


def comment(issue_number: int, text: str) -> None:
    gh("POST", f"/repos/{repo()}/issues/{issue_number}/comments", {"body": text})


def close_issue(issue_number: int, reason: str = "completed") -> None:
    gh("PATCH", f"/repos/{repo()}/issues/{issue_number}", {"state": "closed", "state_reason": reason})


def add_labels(issue_number: int, labels: list[str]) -> None:
    gh("POST", f"/repos/{repo()}/issues/{issue_number}/labels", {"labels": labels})


def remove_label(issue_number: int, label: str) -> None:
    try:
        gh("DELETE", f"/repos/{repo()}/issues/{issue_number}/labels/{urllib.parse.quote(label)}")
    except RuntimeError:
        pass  # label wasn't there


def run_url() -> str:
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    return f"{server}/{repo()}/actions/runs/{os.environ.get('GITHUB_RUN_ID', '')}"


def issue_url(number: int) -> str:
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    return f"{server}/{repo()}/issues/{number}"


# Hidden markers let a bot-created issue carry data (parent number, ADO id) in its body.
def marker(body: str, key: str) -> str | None:
    m = re.search(rf"<!--\s*{re.escape(key)}:(.*?)\s*-->", body or "")
    return m.group(1).strip() if m else None


def make_marker(key: str, value) -> str:
    return f"<!-- {key}:{value} -->"


def step_issues(parent: dict) -> list[dict]:
    """A parent's step issues, from the `steps` marker written at intake (only governance can edit the parent).

    Don't use the sub-issue list for decisions: people with triage access can attach or detach sub-issues,
    e.g. detach an unfinished step so the parent closes as "all done". It's only a fallback for parents
    created before the marker existed.
    """
    steps = marker(parent.get("body"), "steps")
    if steps:
        return [gh("GET", f"/repos/{repo()}/issues/{n}") for n in steps.split(",") if n.strip().isdigit()]
    return gh("GET", f"/repos/{repo()}/issues/{parent['number']}/sub_issues?per_page=100") or []


# --------------------------------------------------------------------------- #
# Issue forms
# --------------------------------------------------------------------------- #
def parse_form(body: str, template_path: str) -> dict:
    """Turn an issue-form body back into {field_id: value} using the template's labels.

    GitHub renders each answer as:
        ### <label>

        <value or _No response_>
    Checkbox answers become a list of the ticked option labels.
    """
    with open(template_path, encoding="utf-8") as f:
        template = yaml.safe_load(f)

    label_to_field = {}
    for item in template.get("body", []):
        if item.get("type") == "markdown" or "id" not in item:
            continue
        label_to_field[item["attributes"]["label"].strip()] = item

    sections = re.split(r"^###\s+", body or "", flags=re.MULTILINE)
    result = {}
    for section in sections[1:]:
        label, _, value = section.partition("\n")
        field = label_to_field.get(label.strip())
        if not field:
            continue
        value = value.strip()
        if field["type"] == "checkboxes":
            result[field["id"]] = [
                m.group(2).strip()
                for m in re.finditer(r"^- \[( |x|X)\] (.*)$", value, flags=re.MULTILINE)
                if m.group(1).lower() == "x"
            ]
        else:
            result[field["id"]] = "" if value == NO_RESPONSE else value
    return result


# --------------------------------------------------------------------------- #
# Azure DevOps (optional: every call is a no-op when ADO settings are missing)
# --------------------------------------------------------------------------- #
def _ado_configured() -> bool:
    return all(os.environ.get(k) for k in ("ADO_ORG_URL", "ADO_PROJECT", "ADO_PAT"))


def _ado(method: str, path: str, data, content_type: str = "application/json"):
    org = os.environ["ADO_ORG_URL"].rstrip("/")
    project = urllib.parse.quote(os.environ["ADO_PROJECT"])
    auth = base64.b64encode(f":{os.environ['ADO_PAT']}".encode()).decode()
    req = urllib.request.Request(
        f"{org}/{project}/_apis/{path}",
        method=method,
        data=json.dumps(data).encode(),
        headers={"Authorization": f"Basic {auth}", "Content-Type": content_type},
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read() or b"null")


def ado_comment(work_item: str | int | None, html: str) -> None:
    if not work_item or not _ado_configured():
        print(f"[ado] skipped comment (work item={work_item!r}, configured={_ado_configured()})")
        return
    try:
        _ado("POST", f"wit/workItems/{work_item}/comments?api-version=7.1-preview.4", {"text": html})
    except Exception as err:  # never fail the pipeline because of a status update
        print(f"[ado] comment failed: {err}", file=sys.stderr)


def ado_update(work_item: str | int | None, state: str | None = None, link: str | None = None) -> None:
    """Optionally move the work item to `state` and/or attach a hyperlink."""
    if not work_item or not _ado_configured():
        return
    ops = []
    if state:
        ops.append({"op": "add", "path": "/fields/System.State", "value": state})
    if link:
        ops.append({"op": "add", "path": "/relations/-",
                    "value": {"rel": "Hyperlink", "url": link, "attributes": {"comment": "GitHub tracking issue"}}})
    if not ops:
        return
    try:
        _ado("PATCH", f"wit/workitems/{work_item}?api-version=7.1", ops, "application/json-patch+json")
    except Exception as err:
        print(f"[ado] update failed: {err}", file=sys.stderr)


# --------------------------------------------------------------------------- #
# Misc
# --------------------------------------------------------------------------- #
def set_output(key: str, value) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{key}={value}\n")
    print(f"[output] {key}={value}")


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")


def pascal(text: str) -> str:
    parts = re.split(r"[^A-Za-z0-9]+", text or "")
    return "".join(p[:1].upper() + p[1:] for p in parts if p)


def load_form() -> dict:
    with open(os.path.join(WORK_DIR, "form.json"), encoding="utf-8") as f:
        return json.load(f)
