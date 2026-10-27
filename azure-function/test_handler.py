"""Run: python test_handler.py  (no Azure or network needed; GitHub call is stubbed)."""
import base64
import json
import os
import unittest
from unittest import mock

os.environ.update(HOOK_USERNAME="ado-hook", HOOK_PASSWORD="s3cret", TARGET_STATE="Approved",
                  GITHUB_REPO="org/repo", GITHUB_DISPATCH_TOKEN="x")
import handler  # noqa: E402

AUTH = "Basic " + base64.b64encode(b"ado-hook:s3cret").decode()
with open(os.path.join(os.path.dirname(__file__), "sample-ado-payload.json")) as f:
    SAMPLE = json.load(f)


class HandlerTests(unittest.TestCase):
    def test_rejects_bad_auth(self):
        self.assertEqual(handler.handle("Basic bm9wZTpub3Bl", SAMPLE)[0], 401)

    def test_dispatches_on_approval(self):
        with mock.patch.object(handler, "dispatch_to_github", return_value=204) as d:
            status, _ = handler.handle(AUTH, SAMPLE)
        self.assertEqual(status, 200)
        sent = d.call_args[0][0]
        self.assertEqual(sent["api_name"], "member-api")
        self.assertEqual(sent["ado_work_item"], "12345")
        self.assertEqual(sent["spec_location"], "specs/member-api.yaml")
        self.assertEqual(sent["requested_by"], "jdoe@example.com")

    def test_ignores_other_state_changes(self):
        payload = json.loads(json.dumps(SAMPLE))
        payload["resource"]["fields"]["System.State"]["newValue"] = "Active"
        with mock.patch.object(handler, "dispatch_to_github") as d:
            status, msg = handler.handle(AUTH, payload)
        self.assertEqual(status, 200)
        self.assertIn("ignored", msg)
        d.assert_not_called()

    def test_falls_back_to_title(self):
        payload = json.loads(json.dumps(SAMPLE))
        del payload["resource"]["revision"]["fields"]["Custom.APIName"]
        self.assertEqual(handler.extract_intake(payload)["api_name"], "member-api")


if __name__ == "__main__":
    unittest.main()
