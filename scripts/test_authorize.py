"""Run from the repo root: python scripts/test_authorize.py  (GitHub API is stubbed, no network)."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))
os.environ.update(GITHUB_REPOSITORY="org/repo", GOVERNANCE="@gov")
import authorize  # noqa: E402

BOT = {"login": "github-actions[bot]"}
ISSUES = {
    "/repos/org/repo/issues/1": {"number": 1, "user": BOT, "body": "**Owners:** @alice, @Bob\n<!-- api:member-api -->"},
    "/repos/org/repo/issues/2": {"number": 2, "user": BOT,
                                 "body": "<!-- parent:1 -->\n<!-- step:codegen -->\n<!-- api:member-api -->"},
    # Someone hand-crafted an issue that looks like a step issue and lists themselves as owner.
    "/repos/org/repo/issues/9": {"number": 9, "user": {"login": "mallory"},
                                 "body": "**Owners:** @mallory\n<!-- parent:9 -->\n<!-- step:codegen -->\n<!-- api:member-api -->"},
}


def fake_gh(method, path, data=None, token=None):
    if path not in ISSUES:
        raise RuntimeError("404")
    return ISSUES[path]


def form(tracking="2", api="member-api"):
    return {"tracking_issue": tracking, "api_name": api}


@mock.patch.object(authorize, "gh", fake_gh)
class AuthorizeTests(unittest.TestCase):
    def test_owner_allowed_case_insensitive(self):
        self.assertIsNone(authorize.check_step("codegen", form(), "alice"))
        self.assertIsNone(authorize.check_step("codegen", form(), "bob"))

    def test_governance_allowed(self):
        self.assertIsNone(authorize.check_step("codegen", form(), "gov"))

    def test_other_team_rejected(self):
        self.assertIn("isn't an owner", authorize.check_step("codegen", form(), "carol"))

    def test_wrong_step_rejected(self):
        self.assertIsNotNone(authorize.check_step("design", form(), "alice"))

    def test_api_name_changed_rejected(self):
        self.assertIsNotNone(authorize.check_step("codegen", form(api="claims-api"), "alice"))

    def test_fake_step_issue_rejected(self):
        self.assertIsNotNone(authorize.check_step("codegen", form(tracking="9"), "mallory"))

    def test_missing_issue_rejected(self):
        self.assertIsNotNone(authorize.check_step("codegen", form(tracking="404"), "alice"))
        self.assertIsNotNone(authorize.check_step("codegen", form(tracking=""), "alice"))

    def test_team_needs_token(self):
        with mock.patch.dict(os.environ, {"GOVERNANCE": "platform-gov"}):
            os.environ.pop("TEAM_READ_TOKEN", None)
            self.assertIsNotNone(authorize.check_step("codegen", form(), "gov"))


class RejectTests(unittest.TestCase):
    """A rejected action must leave the owner's submission as it was."""

    def run_reject(self, action, events=(), prev_title="", prev_body=""):
        calls = []
        def gh(method, path, data=None, token=None):
            calls.append((method, path, data))
            return list(events) if path.endswith("/events?per_page=100") else {}
        with mock.patch.object(authorize, "gh", gh), \
             mock.patch.object(authorize, "comment") as comment, \
             mock.patch.object(authorize, "close_issue") as close:
            authorize.reject(5, "carol", "not an owner", action, prev_title, prev_body)
        return calls, comment, close

    def test_opened_closes_own_issue(self):
        calls, comment, close = self.run_reject("opened")
        close.assert_called_once_with(5, "not_planned")
        self.assertEqual(calls, [])

    def test_edited_restores_previous_body_and_keeps_state(self):
        calls, comment, close = self.run_reject("edited", prev_body="owner's answers")
        self.assertEqual(calls, [("PATCH", "/repos/org/repo/issues/5", {"body": "owner's answers"})])
        close.assert_not_called()
        self.assertIn("Reverted @carol's edit", comment.call_args[0][1])

    def test_edited_title_only(self):
        calls, _, _ = self.run_reject("edited", prev_title="[Codegen] member-api")
        self.assertEqual(calls[0][2], {"title": "[Codegen] member-api"})

    def test_reopened_closes_with_previous_reason(self):
        events = [{"event": "closed", "state_reason": "not_planned"}, {"event": "reopened"},
                  {"event": "closed", "state_reason": "completed"}, {"event": "reopened"}]
        _, _, close = self.run_reject("reopened", events=events)
        close.assert_called_once_with(5, "completed")

    def test_reopened_without_history_defaults_to_completed(self):
        _, _, close = self.run_reject("reopened")
        close.assert_called_once_with(5, "completed")


if __name__ == "__main__":
    unittest.main()
