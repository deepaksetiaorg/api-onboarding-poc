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


if __name__ == "__main__":
    unittest.main()
