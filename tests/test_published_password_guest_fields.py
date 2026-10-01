import copy
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import rotate_guest_password as rgp  # noqa: E402
import setup_guest_wlan  # noqa: E402

CFG = {"api_url": "https://api.mist.com", "token": "tok", "org_id": "org",
       "wlan_id": "w1", "ssid": "Guest", "backup_json": False}


def _wlan(auth_type="open", portal_auth="password", passphrase=True):
    wlan = {"id": "w1", "ssid": "Guest",
            "portal": {"auth": portal_auth, "password": "apples"}}
    if auth_type is not None:
        wlan["auth"] = {"type": auth_type}
        if auth_type == "psk":
            wlan["auth"]["psk"] = "old-wifi-psk"
    if passphrase is not None:
        wlan["portal"]["passphrase_enabled"] = passphrase
    return wlan


class _RotateCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.current = self.dir / "current_password.txt"
        for name, value in (("CURRENT_PASSWORD_FILE", self.current),
                            ("HISTORY_LOG", self.dir / "password_history.log"),
                            ("LOCK_FILE", self.dir / "rotate.lock")):
            p = mock.patch.object(rgp, name, value)
            p.start()
            self.addCleanup(p.stop)

    def _run(self, wlan, dry_run=False):
        state = {"wlan": copy.deepcopy(wlan)}
        self.puts = []

        def fake_request(method, api_url, token, path, body=None):
            if method == "GET":
                return 200, copy.deepcopy(state["wlan"])
            self.puts.append(body)
            state["wlan"]["portal"].update(body["portal"])
            return 200, copy.deepcopy(state["wlan"])

        argv = ["rotate_guest_password.py"] + (["--dry-run"] if dry_run else [])
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(rgp, "load_config", return_value=dict(CFG)), \
                mock.patch.object(rgp, "mist_request", side_effect=fake_request), \
                mock.patch.object(sys, "argv", argv), \
                redirect_stdout(out), redirect_stderr(err):
            try:
                rgp.main()
                code = None
            except SystemExit as e:
                code = e.code
        self.final = state["wlan"]
        return code, out.getvalue(), err.getvalue()


class PassphraseEnabledRequiredTests(_RotateCase):
    def test_false_or_missing_exits_2_without_put(self):
        for flag in (False, None):
            for dry in (False, True):
                with self.subTest(passphrase_enabled=flag, dry_run=dry):
                    code, out, err = self._run(_wlan(passphrase=flag), dry_run=dry)
                    self.assertEqual(code, 2)
                    self.assertEqual(self.puts, [])
                    self.assertFalse(self.current.exists())
                    self.assertIn("passphrase_enabled", err)
                    self.assertEqual(err.count("ERROR:"), 1)
                    self.assertNotIn("would set", out)
                    self.assertEqual(self.final["portal"].get("passphrase_enabled"), flag)

    def test_portal_auth_not_password_still_exits_2(self):
        code, out, err = self._run(_wlan(portal_auth="sso"))
        self.assertEqual(code, 2)
        self.assertEqual(self.puts, [])
        self.assertIn("NOT a guest portal", err)


class OpenSsidTests(_RotateCase):
    def test_rotation_called_guest_wifi_password(self):
        code, out, err = self._run(_wlan("open"))
        self.assertEqual(code, 0)
        self.assertEqual(len(self.puts), 1)
        self.assertIn("Guest WiFi password for SSID 'Guest' updated", out)
        self.assertNotIn("WARNING", err)
        lines = self.current.read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines[0], self.final["portal"]["password"])
        self.assertIn("# Kind: Guest WiFi password", lines)

    def test_dry_run_proceeds(self):
        code, out, _ = self._run(_wlan("open"), dry_run=True)
        self.assertEqual(code, 0)
        self.assertEqual(self.puts, [])
        self.assertIn("would set new Guest WiFi password", out)


class PskSsidTests(_RotateCase):
    def test_psk_warns_and_labels_portal_passphrase(self):
        code, out, err = self._run(_wlan("psk"))
        self.assertEqual(code, 0)
        self.assertEqual(len(self.puts), 1)
        self.assertNotIn("auth", self.puts[0])
        self.assertEqual(self.final["auth"]["psk"], "old-wifi-psk")
        self.assertIn("WARNING", err)
        self.assertIn("auth.psk", err)
        self.assertNotIn("Guest WiFi password", out)
        self.assertIn("Captive-portal passphrase for SSID 'Guest' updated", out)
        text = self.current.read_text(encoding="utf-8")
        lines = text.splitlines()
        self.assertEqual(lines[0], self.final["portal"]["password"])
        self.assertIn("# Kind: captive-portal passphrase", lines)
        self.assertIn("# SSID: Guest", lines)
        self.assertIn("# WLAN ID: w1", lines)
        self.assertNotIn("Guest WiFi password", text)

    def test_missing_auth_type_warns(self):
        code, out, err = self._run(_wlan(auth_type=None), dry_run=True)
        self.assertEqual(code, 0)
        self.assertIn("auth.psk", err)
        self.assertIn("would set new captive-portal passphrase", out)


class SetupPickerTests(unittest.TestCase):
    WLANS = [
        {"id": "w1", "ssid": "Good", "template_id": "tmpl",
         "portal": {"auth": "password", "passphrase_enabled": True}},
        {"id": "w2", "ssid": "NoPass", "template_id": "tmpl",
         "portal": {"auth": "password", "passphrase_enabled": False}},
    ]

    def _run(self, details, inputs):
        responses = iter(details)

        def fake_request(method, api_url, token, path, body=None, with_headers=False):
            if path.startswith("/orgs/org/wlans?"):
                return 200, self.WLANS, {}
            return next(responses)

        out = io.StringIO()
        with mock.patch.object(setup_guest_wlan, "mist_request", side_effect=fake_request), \
                mock.patch("builtins.input", side_effect=list(inputs)), \
                redirect_stdout(out), redirect_stderr(io.StringIO()):
            result = setup_guest_wlan.choose_guest_wlan(CFG, {"id": "tmpl"})
        return result, out.getvalue()

    def test_accepts_password_with_passphrase_enabled(self):
        result, out = self._run([(200, self.WLANS[0])], ["1"])
        self.assertEqual(result["id"], "w1")
        self.assertIn("Validated", out)

    def test_rejects_password_without_passphrase_enabled(self):
        result, out = self._run([(200, self.WLANS[1]), (200, self.WLANS[0])],
                                ["2", "1"])
        self.assertEqual(result["id"], "w1")
        self.assertIn("passphrase_enabled", out)
        self.assertIn("NoPass", out)
        self.assertIs(self.WLANS[1]["portal"]["passphrase_enabled"], False)

    def test_guest_tag_only_when_both(self):
        _, out = self._run([(200, self.WLANS[0])], ["1"])
        tagged = [l for l in out.splitlines() if "<-- guest password portal" in l]
        self.assertEqual(len(tagged), 1)
        self.assertIn("Good", tagged[0])


if __name__ == "__main__":
    unittest.main()
