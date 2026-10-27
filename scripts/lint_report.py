"""Turn Spectral's JSON output into a short, plain-language markdown report.

Usage: python scripts/lint_report.py work/lint.json
Writes work/lint.md. Outputs: passed=true|false, errors, warnings
"""
import json
import os
import sys

from common import WORK_DIR, set_output

SEVERITY = {0: "error", 1: "warning", 2: "info", 3: "hint"}


def main() -> None:
    with open(sys.argv[1], encoding="utf-8") as f:
        text = f.read().strip()
    results = json.loads(text) if text else []

    errors = [r for r in results if r.get("severity") == 0]
    warnings = [r for r in results if r.get("severity") == 1]

    def row(r):
        where = ".".join(str(p) for p in r.get("path", [])) or "(root)"
        line = r.get("range", {}).get("start", {}).get("line")
        loc = f"line {line + 1}" if isinstance(line, int) else ""
        return f"| {SEVERITY.get(r.get('severity'), '?')} | `{where}` {loc} | {r.get('message', '').strip()} |"

    lines = []
    if not errors:
        lines.append("### ✅ Design check passed")
        if warnings:
            lines.append(f"\n{len(warnings)} suggestion(s) to consider (not blocking):")
    else:
        lines.append(f"### Design check: {len(errors)} thing(s) to fix")
        lines.append("\nFix the items marked **error** in your spec, then edit this issue to run the check again.")
    shown = (errors + warnings)[:40]
    if shown:
        lines += ["", "| Type | Where | What to change |", "|---|---|---|", *[row(r) for r in shown]]
    if len(errors + warnings) > len(shown):
        lines.append(f"\n_...and {len(errors + warnings) - len(shown)} more. See the workflow log for the full list._")

    with open(os.path.join(WORK_DIR, "lint.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    set_output("passed", "false" if errors else "true")
    set_output("errors", len(errors))
    set_output("warnings", len(warnings))


if __name__ == "__main__":
    main()
