"""Create one parent tracking issue + three child issues (design, codegen, proxy) for an API.

Called by the `intake` workflow when ADO marks an intake as approved (or manually for demos).
Env: API_NAME (required), OWNERS, ADO_WORK_ITEM, SPEC_LOCATION, REQUESTED_BY, ADO_TITLE
"""
import os
import sys
import urllib.parse

from authorize import MAX_ASSIGNEES, entries, format_owners, owners_note, sync_assignees, users
from common import (ado_comment, ado_update, comment, gh, issue_url, make_marker, marker, repo,
                    set_output, slugify)

STEPS = [
    # key,     template file,          title prefix, what the step does
    ("design", "design-request.yml", "[Design]", "Automated design check of the OpenAPI spec against API standards."),
    ("codegen", "codegen-request.yml", "[Codegen]", "Generate server or client code from the spec."),
    ("proxy", "proxy-request.yml", "[Proxy]", "Build the Apigee proxy bundle and deploy it to dev/test."),
]


def find_existing_parent(ado_id: str) -> dict | None:
    """Avoid duplicates if ADO fires the same event twice."""
    if not ado_id:
        return None
    issues = gh("GET", f"/repos/{repo()}/issues?labels=api-request&state=open&per_page=100")
    return next((i for i in issues if marker(i.get("body"), "ado") == ado_id), None)


def form_link(template: str, title: str, fields: dict) -> str:
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    query = urllib.parse.urlencode({"template": template, "title": title, **{k: v for k, v in fields.items() if v}})
    return f"{server}/{repo()}/issues/new?{query}"


def main() -> None:
    api_name = slugify(os.environ.get("API_NAME", ""))
    if not api_name:
        sys.exit("API_NAME is required")
    ado_id = (os.environ.get("ADO_WORK_ITEM") or "").strip()
    spec = (os.environ.get("SPEC_LOCATION") or "").strip()
    requested_by = (os.environ.get("REQUESTED_BY") or "").strip()
    ado_title = (os.environ.get("ADO_TITLE") or "").strip()
    owners = entries(os.environ.get("OWNERS"))

    existing = find_existing_parent(ado_id)
    if existing:
        print(f"Parent issue already exists: #{existing['number']}")
        set_output("parent_issue", existing["number"])
        return

    # 1) Parent issue (body is finalised once children exist)
    parent = gh("POST", f"/repos/{repo()}/issues", {
        "title": f"[API] {api_name}",
        "labels": ["api-request"],
        "body": "Setting up...",
    })
    pnum = parent["number"]

    # 2) Children, each linked as a native sub-issue of the parent
    rows, step_numbers = [], []
    for key, template, prefix, purpose in STEPS:
        child = gh("POST", f"/repos/{repo()}/issues", {
            "title": f"{prefix} {api_name}",
            "labels": ["api-step", f"step:{key}"],
            "body": "Setting up...",
        })
        cnum = child["number"]
        link = form_link(template, f"{prefix} {api_name}", {
            "api_name": api_name,
            "tracking_issue": str(cnum),
            "ado_work_item": ado_id,
            "spec_location": spec,
        })
        body = "\n".join([
            f"## {prefix.strip('[]')} step for `{api_name}`",
            "",
            purpose,
            "",
            f"### 👉 [Fill in the details here]({link})",
            "",
            "The link opens a short form with the API name already filled in. "
            "Once you submit it, the automation runs and posts the result back here. "
            "This issue closes automatically when the step is done.",
            "",
            f"Only the owners listed on #{pnum} (and the governance team) can submit this form.",
            "",
            f"Part of #{pnum}.",
            "",
            make_marker("parent", pnum),
            make_marker("ado", ado_id),
            make_marker("step", key),
            make_marker("api", api_name),
        ])
        gh("PATCH", f"/repos/{repo()}/issues/{cnum}", {"body": body})
        gh("POST", f"/repos/{repo()}/issues/{pnum}/sub_issues", {"sub_issue_id": child["id"]})
        rows.append(f"| {prefix.strip('[]')} | #{cnum} | [Open form]({link}) |")
        step_numbers.append(cnum)

    # 3) Final parent body
    parent_body = "\n".join([
        f"## API onboarding: `{api_name}`",
        "",
        f"ADO intake: **{ado_title or ado_id or 'n/a'}**" + (f" (work item {ado_id})" if ado_id else ""),
        f"Requested by: {requested_by or 'n/a'}",
        f"**Owners:** {format_owners(owners)}",
        "_Only owners and the governance team can submit the step forms. Governance can edit the line above to change owners._",
        f"Spec: `{spec or 'not provided yet'}`",
        "",
        "Each step below is its own issue. Fill in its form and the automation takes it from there. "
        "Progress shows in the **Sub-issues** panel, and this issue closes when all three are done.",
        "",
        "| Step | Issue | Form |",
        "|---|---|---|",
        *rows,
        "",
        make_marker("ado", ado_id),
        make_marker("api", api_name),
        make_marker("steps", ",".join(map(str, step_numbers))),  # source of truth for "all steps done"
    ])
    gh("PATCH", f"/repos/{repo()}/issues/{pnum}", {"body": parent_body})

    # 4) Assign individual owners to the step issues (display only, access comes from the Owners line).
    #    Teams aren't expanded into assignees: they're mentioned, so GitHub notifies the current members.
    people = users(owners)
    bad = sync_assignees(step_numbers, people, [])
    note = owners_note([o for o in owners if not o.startswith("@")], bad,
                       extra=len(people) - len(bad) - MAX_ASSIGNEES)
    if note:
        comment(pnum, note)

    # 5) Tell ADO where to follow along
    ado_update(ado_id, link=issue_url(pnum))
    ado_comment(ado_id, f"GitHub tracking issue created: <a href='{issue_url(pnum)}'>#{pnum}</a> "
                        f"with design, code generation and proxy steps.")

    print(f"Created parent #{pnum} with 3 sub-issues")
    set_output("parent_issue", pnum)


if __name__ == "__main__":
    main()
