"""Who may do what. Lists are comma-separated GitHub usernames (@alice) or team slugs in this repo's org.

  python scripts/authorize.py governance
      Fails unless SENDER is in GOVERNANCE. Guards the intake workflow.
  python scripts/authorize.py <design|codegen|proxy>
      Allows SENDER only if they are an owner of the API (the "Owners:" line on its parent issue)
      or in GOVERNANCE. Otherwise comments on the submission and closes it. Output: allowed=true|false

Env: SENDER, GOVERNANCE, ISSUE_BODY, ISSUE_NUMBER, TEAM_READ_TOKEN (read:org, only needed for team slugs)

Owners are read from bot-created issues, never from the form, so they can't be faked.
Only people with write access can edit those issues, so only governance can change owners.
"""
import os
import re
import sys

from common import close_issue, comment, gh, marker, parse_form, repo, set_output
from read_form import TEMPLATES

BOT = "github-actions[bot]"
OWNERS_RE = re.compile(r"^\*\*Owners:\*\*(.*)$", re.MULTILINE)


def entries(text: str | None) -> list[str]:
    return [e.strip() for e in (text or "").split(",") if e.strip()]


def is_member(user: str, entry: str) -> bool:
    if entry.startswith("@"):
        return entry[1:].lower() == user.lower()
    token = os.environ.get("TEAM_READ_TOKEN")
    if not token:
        print(f"TEAM_READ_TOKEN is not set, so team '{entry}' can't be checked")
        return False
    try:
        m = gh("GET", f"/orgs/{repo().split('/')[0]}/teams/{entry}/memberships/{user}", token=token)
    except RuntimeError:
        return False  # 404: not a member, or no such team
    return m.get("state") == "active"


def in_any(user: str, allowed: list[str]) -> bool:
    return any(is_member(user, e) for e in allowed)


def bot_issue(number) -> dict | None:
    try:
        issue = gh("GET", f"/repos/{repo()}/issues/{number}")
    except RuntimeError:
        return None
    return issue if (issue.get("user") or {}).get("login") == BOT else None


def check_step(step: str, form: dict, user: str) -> str | None:
    """Return None if allowed, else the reason to show the user."""
    use_link = "Please use the form link on your step issue and leave the pre-filled fields as they are."
    tracking = (form.get("tracking_issue") or "").lstrip("#")
    child = bot_issue(tracking) if tracking.isdigit() else None
    if not child or marker(child.get("body"), "step") != step:
        return f"the tracking issue isn't a {step} step issue. {use_link}"
    if marker(child.get("body"), "api") != form.get("api_name"):
        return f"the API name doesn't match #{tracking}. {use_link}"
    parent = bot_issue(marker(child.get("body"), "parent"))
    m = OWNERS_RE.search((parent or {}).get("body") or "")
    owners = entries(m.group(1)) if m else []
    if in_any(user, owners + entries(os.environ.get("GOVERNANCE"))):
        return None
    listed = ", ".join(owners) or "none yet"
    return (f"@{user} isn't an owner of `{form['api_name']}` (owners: {listed}). "
            f"Ask the governance team to add you on #{parent['number'] if parent else '?'}.")


def main() -> None:
    mode = sys.argv[1]
    user = os.environ["SENDER"]

    if mode == "governance":
        if not in_any(user, entries(os.environ.get("GOVERNANCE"))):
            sys.exit(f"Only the governance team can start an onboarding. @{user} is not in the GOVERNANCE variable.")
        print(f"@{user} is in governance")
        return

    form = parse_form(os.environ.get("ISSUE_BODY", ""), TEMPLATES[mode])
    reason = check_step(mode, form, user)
    if reason:
        number = int(os.environ["ISSUE_NUMBER"])
        comment(number, f"🔒 Not run: {reason}")
        close_issue(number, "not_planned")
    print(reason or f"@{user} is allowed")
    set_output("allowed", str(reason is None).lower())


if __name__ == "__main__":
    main()
