import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import setup_guest_wlan  # noqa: E402

OLD_ENV = {
    "MIST_API_URL": "https://api.mist.com",
    "MIST_API_TOKEN": "old-token",
    "MIST_ORG_ID": "old-org",
    "MIST_WLAN_ID": "old-wlan",
    "MIST_WLAN_SSID": "Old-Guest",
}
NEW_CREDS = {
    "MIST_API_URL": "https://api.eu.mist.com",
    "MIST_API_TOKEN": "new-token",
    "MIST_ORG_ID": "new-org",
}
# org id, token, cloud number 6 (EMEA 01 -> api.eu.mist.com)
CRED_INPUTS = ["new-org", "new-token", "6"]


class SetupDefersCredentialWriteTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        d = Path(self._tmp.name)
        self.env = d / ".env"
        self.env.write_text("".join(f"{k}={v}\n" for k, v in OLD_ENV.items()),
                            encoding="utf-8")
        (d / "current_password.txt").write_text("apples\n", encoding="utf-8")
        for name, val in (("ENV_PATH", self.env),
                          ("CURRENT_PASSWORD_FILE", d / "current_password.txt"),
                          ("HISTORY_LOG", d / "password_history.log"),
                          ("LOCK_FILE", d / "rotate.lock")):
            p = mock.patch.object(setup_guest_wlan, name, val)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(setup_guest_wlan, "validate_credentials",
                              return_value=(True, "New Org"))
        p.start()
        self.addCleanup(p.stop)

    def _assert_old_env(self):
        env = setup_guest_wlan.read_env()
        for key, val in OLD_ENV.items():
            self.assertEqual(env.get(key), val, key)

    def test_credential_step_does_not_write_env(self):
        with mock.patch("builtins.input", side_effect=CRED_INPUTS), \
                redirect_stdout(io.StringIO()) as out:
            cfg = setup_guest_wlan.collect_and_store_credentials()
        self.assertEqual(cfg["api_url"], NEW_CREDS["MIST_API_URL"])
        self.assertEqual(cfg["token"], "new-token")
        self.assertEqual(cfg["org_id"], "new-org")
        self.assertNotIn("Saved credentials", out.getvalue())
        self._assert_old_env()

    def test_later_step_failure_leaves_env_unchanged(self):
        upsert = mock.Mock(wraps=setup_guest_wlan.upsert_env)
        with mock.patch("builtins.input", side_effect=CRED_INPUTS), \
                mock.patch.object(setup_guest_wlan, "upsert_env", upsert), \
                mock.patch.object(setup_guest_wlan, "choose_template",
                                  side_effect=RuntimeError("no templates")), \
                redirect_stdout(io.StringIO()):
            with self.assertRaises(RuntimeError):
                setup_guest_wlan.main()
        upsert.assert_not_called()
        self._assert_old_env()

    def test_later_step_exit_leaves_env_unchanged(self):
        with mock.patch("builtins.input", side_effect=CRED_INPUTS), \
                mock.patch.object(setup_guest_wlan, "choose_template",
                                  return_value={"id": "tmpl", "name": "T"}), \
                mock.patch.object(setup_guest_wlan, "choose_guest_wlan",
                                  side_effect=SystemExit(3)), \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as cm:
                setup_guest_wlan.main()
        self.assertEqual(cm.exception.code, 3)
        self._assert_old_env()

    def test_success_writes_creds_and_wlan_in_one_locked_write(self):
        calls = []
        real_upsert = setup_guest_wlan.upsert_env

        def upsert(updates):
            calls.append(dict(updates))
            if os.name != "nt":
                import fcntl
                with open(setup_guest_wlan.LOCK_FILE, "a+", encoding="utf-8") as f:
                    with self.assertRaises(OSError):
                        fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return real_upsert(updates)

        with mock.patch("builtins.input", side_effect=CRED_INPUTS), \
                mock.patch.object(setup_guest_wlan, "upsert_env", side_effect=upsert), \
                mock.patch.object(setup_guest_wlan, "choose_template",
                                  return_value={"id": "tmpl", "name": "T"}), \
                mock.patch.object(setup_guest_wlan, "choose_guest_wlan",
                                  return_value={"id": "new-wlan", "ssid": "New-Guest"}), \
                mock.patch.object(setup_guest_wlan, "prompt_yes_no", return_value=False), \
                redirect_stdout(io.StringIO()):
            setup_guest_wlan.main()

        self.assertEqual(len(calls), 1)
        for key, val in NEW_CREDS.items():
            self.assertEqual(calls[0].get(key), val, key)
        self.assertEqual(calls[0].get("MIST_WLAN_ID"), "new-wlan")
        env = setup_guest_wlan.read_env()
        for key, val in NEW_CREDS.items():
            self.assertEqual(env.get(key), val, key)
        self.assertEqual(env.get("MIST_WLAN_ID"), "new-wlan")
        self.assertEqual(env.get("MIST_WLAN_SSID"), "New-Guest")


if __name__ == "__main__":
    unittest.main()
