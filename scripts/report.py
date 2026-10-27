"""Post results back to GitHub (submission + tracking issue) and ADO, and close things when done.

Usage:
  python scripts/report.py started
  python scripts/report.py success  [--details FILE] [--artifact-url URL] [--extra TEXT]
  python scripts/report.py needs-changes --details FILE
  python scripts/report.py failure
  python scripts/report.py check-parent --child N     (used when a person closes a step by hand)
"""
import argparse
import os

from common import (add_labels, ado_comment, ado_update, close_issue, comment, gh, issue_url,
                    load_form, marker, remove_label, repo, run_url)

STEP_NAMES = {"design": "Design check", "codegen": "Code generation", "proxy": "Apigee proxy"}


def read(path: str | None) -> str:
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    return ""


def check_parent(child_number: int) -> None:
    """Close the parent tracking issue (and move ADO forward) once every step is closed."""
    child = gh("GET", f"/repos/{repo()}/issues/{child_number}")
    parent = marker(child.get("body"), "parent")
    if not parent:
        return
    subs = gh("GET", f"/repos/{repo()}/issues/{parent}/sub_issues?per_page=100")
    open_steps = [s for s in subs if s["state"] == "open"]
    if open_steps:
        print(f"Parent #{parent}: {len(subs) - len(open_steps)}/{len(subs)} steps done")
        return
    ado_id = marker(child.get("body"), "ado")
    comment(int(parent), "🎉 All steps are done: design, code generation and proxy. Closing this tracking issue.")
    close_issue(int(parent))
    ado_comment(ado_id, f"All GitHub steps finished. Tracking issue <a href='{issue_url(int(parent))}'>#{parent}</a> closed.")
    ado_update(ado_id, state=os.environ.get("ADO_DONE_STATE") or None)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("status", choices=["started", "success", "needs-changes", "failure", "check-parent"])
    ap.add_argument("--details")
    ap.add_argument("--artifact-url")
    ap.add_argument("--extra", default="")
    ap.add_argument("--child", type=int)
    args = ap.parse_args()

    if args.status == "check-parent":
        check_parent(args.child)
        return

    form = load_form()
    step = STEP_NAMES.get(form.get("step"), form.get("step"))
    sub = form.get("submission_issue")
    tracking = int(form["tracking_issue"]) if str(form.get("tracking_issue", "")).isdigit() else None
    ado_id = form.get("ado_work_item")
    details = read(args.details)

    if args.status == "started":
        comment(sub, f"⏳ Thanks! Working on your {step.lower()} request. [Watch progress]({run_url()})")
        return

    if args.status == "needs-changes":
        comment(sub, details or "Some answers need a fix. Edit this issue to try again.")
        add_labels(sub, ["needs-changes"])
        if tracking:
            comment(tracking, f"{step}: waiting on fixes in #{sub}.")
        return

    if args.status == "failure":
        comment(sub, f"❌ Something went wrong on our side while running the {step.lower()}. "
                     f"The API platform team has been notified. [Run log]({run_url()})\n\n"
                     f"You can edit this issue to try again.")
        ado_comment(ado_id, f"{step} failed for <a href='{issue_url(sub)}'>#{sub}</a>. "
                            f"<a href='{run_url()}'>Run log</a>")
        return

    # success
    download = f"\n\n### ⬇️ [Download from the workflow run]({args.artifact_url})\n" \
               f"_Scroll to **Artifacts** at the bottom of the run page. Links expire after the retention period._" \
        if args.artifact_url else ""
    body = f"### ✅ {step} done\n\n{details}{download}\n\n{args.extra}".strip()
    comment(sub, body)
    remove_label(sub, "needs-changes")
    close_issue(sub)
    if tracking:
        comment(tracking, f"✅ {step} finished in #{sub}.{' [Download](' + args.artifact_url + ')' if args.artifact_url else ''}")
        close_issue(tracking)
        check_parent(tracking)
    ado_comment(ado_id, f"✅ {step} finished: <a href='{issue_url(sub)}'>#{sub}</a>"
                        + (f" | <a href='{args.artifact_url}'>download</a>" if args.artifact_url else ""))


if __name__ == "__main__":
    main()
