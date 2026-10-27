#!/usr/bin/env bash
# Pretend to be ADO: send the same event the Azure Function sends, straight to GitHub.
# Usage: ./scripts/demo_trigger.sh <org/repo> [api-name] [ado-work-item] [owners, e.g. "@alice, @bob"]
# Needs the GitHub CLI (gh) logged in with access to the repo.
set -euo pipefail
REPO="${1:?usage: demo_trigger.sh <org/repo> [api-name] [ado-work-item] [owners]}"
API="${2:-member-api}"
WI="${3:-}"
OWNERS="${4:-}"

gh api "repos/$REPO/dispatches" --method POST --input - <<EOF
{
  "event_type": "ado-intake-approved",
  "client_payload": {
    "api_name": "$API",
    "owners": "$OWNERS",
    "ado_work_item": "$WI",
    "title": "$API (demo intake)",
    "spec_location": "specs/member-api.yaml",
    "requested_by": "demo"
  }
}
EOF
echo "Sent. Watch: https://github.com/$REPO/actions"
