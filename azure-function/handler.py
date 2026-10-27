"""ADO "work item updated" webhook -> GitHub repository_dispatch.

Kept free of Azure imports so it can be unit-tested locally (see test_handler.py).

Settings (app settings / environment variables):
  GITHUB_REPO            org/repo that holds the workflows, e.g. example-org/api-onboarding
  GITHUB_DISPATCH_TOKEN  fine-grained PAT or GitHub App token with Contents: write on that repo
  HOOK_USERNAME / HOOK_PASSWORD   basic-auth credentials you also enter in the ADO service hook
  TARGET_STATE           ADO state that starts the pipeline (default: Approved)
  WORK_ITEM_TYPE         optional, only react to this type (e.g. "API Intake")
  API_NAME_FIELD         ADO field holding the API name (default: Custom.APIName; falls back to title)
  SPEC_FIELD             ADO field holding the spec link (default: Custom.SpecLocation)
"""
import base64
import hmac
import json
import os
import re
import urllib.request


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")


def check_basic_auth(header: str | None) -> bool:
    user, pwd = os.environ.get("HOOK_USERNAME", ""), os.environ.get("HOOK_PASSWORD", "")
    if not user or not pwd:
        return False  # refuse to run unprotected
    if not header or not header.startswith("Basic "):
        return False
    try:
        got_user, _, got_pwd = base64.b64decode(header[6:]).decode().partition(":")
    except Exception:
        return False
    return hmac.compare_digest(got_user, user) and hmac.compare_digest(got_pwd, pwd)


def extract_intake(payload: dict) -> dict | None:
    """Return the dispatch payload if this event is 'intake moved to TARGET_STATE', else None."""
    if payload.get("eventType") != "workitem.updated":
        return None
    resource = payload.get("resource") or {}
    state_change = (resource.get("fields") or {}).get("System.State") or {}
    target = os.environ.get("TARGET_STATE", "Approved")
    if state_change.get("newValue") != target or state_change.get("oldValue") == target:
        return None

    fields = (resource.get("revision") or {}).get("fields") or {}
    wanted_type = os.environ.get("WORK_ITEM_TYPE")
    if wanted_type and fields.get("System.WorkItemType") != wanted_type:
        return None

    title = fields.get("System.Title", "")
    api_name = _slug(fields.get(os.environ.get("API_NAME_FIELD", "Custom.APIName")) or title)
    if not api_name:
        return None
    requested = fields.get("System.CreatedBy")
    if isinstance(requested, dict):
        requested = requested.get("uniqueName") or requested.get("displayName")
    return {
        "api_name": api_name,
        "ado_work_item": str(resource.get("workItemId") or (resource.get("revision") or {}).get("id") or ""),
        "title": title,
        "spec_location": fields.get(os.environ.get("SPEC_FIELD", "Custom.SpecLocation"), "") or "",
        "requested_by": requested or "",
    }


def dispatch_to_github(client_payload: dict) -> int:
    req = urllib.request.Request(
        f"https://api.github.com/repos/{os.environ['GITHUB_REPO']}/dispatches",
        method="POST",
        data=json.dumps({"event_type": "ado-intake-approved", "client_payload": client_payload}).encode(),
        headers={
            "Authorization": f"Bearer {os.environ['GITHUB_DISPATCH_TOKEN']}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req) as resp:
        return resp.status  # 204 on success


def handle(auth_header: str | None, payload: dict) -> tuple[int, str]:
    """Returns (http_status, message). Ignored events still return 200 so ADO doesn't retry."""
    if not check_basic_auth(auth_header):
        return 401, "unauthorized"
    intake = extract_intake(payload)
    if not intake:
        return 200, "ignored: not an approval of an intake work item"
    status = dispatch_to_github(intake)
    return 200, f"dispatched {intake['api_name']} (work item {intake['ado_work_item']}), GitHub status {status}"
