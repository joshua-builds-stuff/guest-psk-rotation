import io
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import setup_guest_wlan  # noqa: E402

CFG = {"api_url": "https://api.mist.com", "token": "tok", "org_id": "org"}
TEMPLATE = {"id": "tmpl"}
WLANS = [
    {"id": "w1", "ssid": "Guest", "template_id": "tmpl",
     "portal": {"auth": "password"}},
    {"id": "w2", "ssid": "Staff", "template_id": "tmpl",
     "portal": {"auth": "sso"}},
]


def _run(detail_responses, inputs):
    """Run choose_guest_wlan with scripted API responses and prompt input."""
    responses = iter(detail_responses)

    def fake_request(method, api_url, token, path, body=None):
        if path == "/orgs/org/wlans":
            return 200, WLANS
        return next(responses)

    out, err = io.StringIO(), io.StringIO()
    with mock.patch.object(setup_guest_wlan, "mist_request", side_effect=fake_request), \
            mock.patch("builtins.input", side_effect=list(inputs)), \
            redirect_stdout(out), redirect_stderr(err):
        try:
            result = setup_guest_wlan.choose_guest_wlan(CFG, TEMPLATE)
            code = None
        except SystemExit as e:
            result, code = None, e.code
    return result, code, out.getvalue(), err.getvalue()


class WlanValidationTests(unittest.TestCase):
    def test_valid_password_portal_accepted(self):
        result, code, out, _ = _run([(200, WLANS[0])], ["1"])
        self.assertEqual(result["id"], "w1")
        self.assertIn("Validated", out)

    def test_real_auth_mismatch_still_reported(self):
        result, _, out, _ = _run([(200, WLANS[1]), (200, WLANS[0])], ["2", "1"])
        self.assertEqual(result["id"], "w1")
        self.assertIn("NOT a guest portal", out)
        self.assertIn("'sso'", out)

    def test_401_and_403_exit_3_without_blaming_ssid(self):
        for status in (401, 403):
            with self.subTest(status=status):
                result, code, out, err = _run(
                    [(status, {"detail": "Unauthorized"})], ["1"])
                self.assertIsNone(result)
                self.assertEqual(code, 3)
                self.assertIn(f"HTTP {status}", err)
                self.assertNotIn("NOT a guest portal", out)

    def test_429_retry_then_success(self):
        result, code, out, err = _run(
            [(429, {"detail": "Too Many Requests"}), (200, WLANS[0])],
            ["1", "y"])
        self.assertEqual(result["id"], "w1")
        self.assertIn("HTTP 429", err)
        self.assertNotIn("NOT a guest portal", out)

    def test_500_decline_retry_exits_3(self):
        result, code, out, err = _run([(500, "oops")], ["1", "n"])
        self.assertIsNone(result)
        self.assertEqual(code, 3)
        self.assertIn("HTTP 500", err)
        self.assertNotIn("NOT a guest portal", out)

    def test_404_lets_operator_pick_again(self):
        result, _, out, err = _run(
            [(404, {"detail": "not found"}), (200, WLANS[0])], ["2", "1"])
        self.assertEqual(result["id"], "w1")
        self.assertIn("HTTP 404", err)
        self.assertNotIn("NOT a guest portal", out)

    def test_non_dict_200_is_not_treated_as_mismatch(self):
        result, code, out, err = _run([(200, None)], ["1", "n"])
        self.assertEqual(code, 3)
        self.assertIn("unexpected response body", err)
        self.assertNotIn("NOT a guest portal", out)


if __name__ == "__main__":
    unittest.main()
