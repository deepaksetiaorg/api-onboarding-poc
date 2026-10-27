"""Who may do what. Lists are comma-separated GitHub usernames (@alice) or team slugs in this repo's org.

  python scripts/authorize.py governance
      Fails unless SENDER is in GOVERNANCE. Guards the intake workflow.
  python scripts/authorize.py <design|codegen|proxy>
      Allows SENDER only if they are an owner of the API (the "Owners:" line on its parent issue)
      or in GOVERNANCE. Output: allowed=true|false. If not allowed, nothing runs and the submission
      is put back the way it was, so the owner isn't affected by someone else's action:
        opened   -> their own new issue: comment + close
        edited   -> restore the previous title/body, leave open/closed as it was
        reopened -> close again with the reason it had before
  python scripts/authorize.py guard
      Close/reopen/edit of a parent, step or submission issue by someone not allowed to (see guard_reason)
      is undone: closed -> reopened, reopened -> closed again, edited -> previous title/body restored.

Env: SENDER, GOVERNANCE, ISSUE_BODY, ISSUE_NUMBER, ACTION, PREV_BODY, PREV_TITLE,
     TEAM_READ_TOKEN (read:org, only needed for team slugs)

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
VERB = {"closed": "close", "reopened": "reopen", "edited": "edit"}


def entries(text: str | None) -> list[str]:
    # Owners lines show names as `@alice` (code format, so they don't ping); plain @alice works too.
    return [e.strip().strip("`").strip() for e in (text or "").split(",") if e.strip().strip("`").strip()]


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


# --------------------------------------------------------------------------- #
# Assignees: who is working on a step. Display only. They NEVER grant access:
# access comes from the Owners line, and nothing in this file may read assignees.
# --------------------------------------------------------------------------- #
MAX_ASSIGNEES = 10  # GitHub's limit per issue


def owners_in(body: str | None) -> list[str]:
    m = OWNERS_RE.search(body or "")
    return entries(m.group(1)) if m else []


def format_owners(owners: list[str]) -> str:
    return ", ".join(f"`{o}`" for o in owners)


def users(owners: list[str]) -> list[str]:
    return [o[1:] for o in owners if o.startswith("@")]


def owner_changes(old_body: str, new_body: str) -> tuple[list[str], list[str]]:
    """(added, removed) owners between two versions of a parent issue body. Case-insensitive."""
    old, new = owners_in(old_body), owners_in(new_body)
    old_l, new_l = {o.lower() for o in old}, {o.lower() for o in new}
    return [o for o in new if o.lower() not in old_l], [o for o in old if o.lower() not in new_l]


def assignable(user: str) -> bool:
    try:
        gh("GET", f"/repos/{repo()}/assignees/{user}")  # 204 if they can be assigned
        return True
    except RuntimeError:
        return False  # 404: no such user, or no access to the repo


def sync_assignees(issues: list[int], add: list[str], remove: list[str]) -> list[str]:
    """Assign `add` and unassign `remove` (usernames) on each issue. Returns users who couldn't be assigned."""
    ok = [u for u in add if assignable(u)]
    for number in issues:
        if ok:
            gh("POST", f"/repos/{repo()}/issues/{number}/assignees", {"assignees": ok[:MAX_ASSIGNEES]})
        if remove:
            gh("DELETE", f"/repos/{repo()}/issues/{number}/assignees", {"assignees": remove})
    return [u for u in add if u not in ok]


def owners_note(teams: list[str], unassignable: list[str], extra: int = 0) -> str:
    """Comment text: notify added teams (live membership, so nothing goes stale) and flag bad usernames."""
    org = repo().split("/")[0]
    lines = [f"👥 @{org}/{t}: you're now an owner of this API." for t in teams]
    lines += [f"⚠️ `@{u}` can't be assigned: check the username and that they have access to this repo."
              for u in unassignable]
    if extra > 0:
        lines.append(f"⚠️ Only {MAX_ASSIGNEES} people can be assigned to an issue, {extra} owner(s) weren't assigned "
                     "(they're still owners). Consider using a GitHub team.")
    return "\n".join(lines)


def sync_owner_change(parent: dict, prev_body: str) -> None:
    """Governance edited a parent: assign added owners and unassign removed ones on OPEN steps only."""
    added, removed = owner_changes(prev_body, parent.get("body") or "")
    if not (added or removed):
        return
    subs = gh("GET", f"/repos/{repo()}/issues/{parent['number']}/sub_issues?per_page=100") or []
    open_steps = [s["number"] for s in subs if s.get("state") == "open"]
    bad = sync_assignees(open_steps, users(added), users(removed))
    summary = (f"👥 Owners updated. Added: {format_owners(added) or 'none'}. Removed: {format_owners(removed) or 'none'}. "
               f"Assignees updated on open steps: {', '.join(f'#{n}' for n in open_steps) or 'none'}.")
    note = owners_note([o for o in added if not o.startswith("@")], bad)
    comment(parent["number"], summary + (f"\n\n{note}" if note else ""))


def step_owners(child: dict) -> tuple[list[str], dict | None]:
    """Owners of a step issue, from the Owners line of its bot-created parent."""
    parent = bot_issue(marker(child.get("body"), "parent"))
    return owners_in((parent or {}).get("body")), parent


def linked_step(step: str, form: dict) -> tuple[dict | None, str | None]:
    """The bot-created step issue a form points at, or the reason it doesn't point at a valid one."""
    use_link = "Please use the form link on your step issue and leave the pre-filled fields as they are."
    tracking = (form.get("tracking_issue") or "").lstrip("#")
    child = bot_issue(tracking) if tracking.isdigit() else None
    if not child or marker(child.get("body"), "step") != step:
        return None, f"the tracking issue isn't a {step} step issue. {use_link}"
    if marker(child.get("body"), "api") != form.get("api_name"):
        return None, f"the API name doesn't match #{tracking}. {use_link}"
    return child, None


def check_step(step: str, form: dict, user: str) -> str | None:
    """Return None if allowed, else the reason to show the user."""
    child, reason = linked_step(step, form)
    if reason:
        return reason
    owners, parent = step_owners(child)
    if in_any(user, owners + entries(os.environ.get("GOVERNANCE"))):
        return None
    listed = format_owners(owners) or "none yet"
    return (f"@{user} isn't an owner of `{form['api_name']}` (owners: {listed}). "
            f"Ask the governance team to add you on #{parent['number'] if parent else '?'}.")


def last_close_reason(number: int) -> str:
    events = gh("GET", f"/repos/{repo()}/issues/{number}/events?per_page=100") or []
    closed = [e for e in events if e.get("event") == "closed"]
    return (closed[-1].get("state_reason") if closed else None) or "completed"


def reject(number: int, user: str, reason: str, action: str, prev_title: str, prev_body: str) -> None:
    """Undo the sender's action instead of punishing the issue's owner for it."""
    if action == "edited":
        restore = {k: v for k, v in (("title", prev_title), ("body", prev_body)) if v}
        if restore:
            gh("PATCH", f"/repos/{repo()}/issues/{number}", restore)
        comment(number, f"↩️ Reverted @{user}'s edit, nothing was run. 🔒 {reason}")
    elif action == "reopened":
        close_issue(number, last_close_reason(number))
        comment(number, f"↩️ Closed again, nothing was run. 🔒 {reason}")
    elif action == "closed":
        gh("PATCH", f"/repos/{repo()}/issues/{number}", {"state": "open"})
        comment(number, f"↩️ Reopened, @{user} can't close this. 🔒 {reason}")
    else:
        comment(number, f"🔒 Not run: {reason}")
        close_issue(number, "not_planned")


def guard_reason(issue: dict, user: str, action: str) -> str | None:
    """Close/reopen/edit of a parent, step or submission issue. Return None if allowed, else the reason.

    Parent: governance only. Step: owners may close/reopen, only governance may edit (it holds the links).
    Submission: its author, owners or governance may close (edits/reopens are checked by the step workflows).
    """
    gov = entries(os.environ.get("GOVERNANCE"))
    if user == BOT or in_any(user, gov):
        return None
    labels = {lb["name"] for lb in issue.get("labels", [])}
    by_bot = (issue.get("user") or {}).get("login") == BOT
    if by_bot and "api-request" in labels:
        return "only the governance team can close, reopen or edit an API tracking issue."
    if by_bot and "api-step" in labels:
        if action == "edited":
            return "only the governance team can edit a step issue."
        owners, _ = step_owners(issue)
        return None if in_any(user, owners) else f"only the owners ({format_owners(owners) or 'none yet'}) or governance can {VERB[action]} this step."
    step = next((s for s in TEMPLATES if f"{s}-request" in labels), None)
    if step and action == "closed" and user != (issue.get("user") or {}).get("login"):
        child, _ = linked_step(step, parse_form(issue.get("body", ""), TEMPLATES[step]))
        if child:  # submissions not linked to a real step protect nothing
            owners, _ = step_owners(child)
            if not in_any(user, owners):
                return "only the person who opened it, the API's owners or governance can close a submission."
    return None


def main() -> None:
    mode = sys.argv[1]
    user = os.environ["SENDER"]

    if mode == "governance":
        if not in_any(user, entries(os.environ.get("GOVERNANCE"))):
            sys.exit(f"Only the governance team can start an onboarding. @{user} is not in the GOVERNANCE variable.")
        print(f"@{user} is in governance")
        return

    if mode == "guard":
        number, action = int(os.environ["ISSUE_NUMBER"]), os.environ["ACTION"]
        issue = gh("GET", f"/repos/{repo()}/issues/{number}")
        reason = guard_reason(issue, user, action)
        prev_body = os.environ.get("PREV_BODY", "")
        if reason:
            reject(number, user, reason, action, os.environ.get("PREV_TITLE", ""), prev_body)
        elif action == "edited" and prev_body and (issue.get("user") or {}).get("login") == BOT and any(
                lb["name"] == "api-request" for lb in issue.get("labels", [])):
            sync_owner_change(issue, prev_body)  # governance changed the Owners line
        print(reason or f"@{user} may {VERB[action]} #{number}")
        set_output("allowed", str(reason is None).lower())
        return

    form = parse_form(os.environ.get("ISSUE_BODY", ""), TEMPLATES[mode])
    reason = check_step(mode, form, user)
    if reason:
        reject(int(os.environ["ISSUE_NUMBER"]), user, reason, os.environ.get("ACTION", "opened"),
               os.environ.get("PREV_TITLE", ""), os.environ.get("PREV_BODY", ""))
    print(reason or f"@{user} is allowed")
    set_output("allowed", str(reason is None).lower())


if __name__ == "__main__":
    main()
