import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import setup_guest_wlan  # noqa: E402

PASSWORD = b"apples\r\n# SSID: Guest-WiFi\n"
HISTORY = b"2026-01-01 06:00:00\tGuest-WiFi\tapples\n"
ENV = "MIST_API_TOKEN=t\nMIST_WLAN_ID=old-id\nMIST_WLAN_SSID=Guest-WiFi\n"


class _TmpDirCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.current = self.dir / "current_password.txt"
        self.history = self.dir / "password_history.log"
        self.env = self.dir / ".env"
        for name, value in (("CURRENT_PASSWORD_FILE", self.current),
                            ("HISTORY_LOG", self.history),
                            ("ENV_PATH", self.env),
                            ("LOCK_FILE", self.dir / "rotate.lock")):
            p = mock.patch.object(setup_guest_wlan, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self._tmp.cleanup)
        self.current.write_bytes(PASSWORD)
        self.history.write_bytes(HISTORY)
        self.env.write_text(ENV, encoding="utf-8")

    def _run_main(self, *extra_patches):
        cfg = {"api_url": "https://api.mist.com", "token": "t2", "org_id": "o",
               "org_name": "Org"}
        patches = [
            mock.patch.object(setup_guest_wlan, "collect_and_store_credentials",
                              return_value=cfg),
            mock.patch.object(setup_guest_wlan, "choose_template",
                              return_value={"id": "tmpl", "name": "T"}),
            mock.patch.object(setup_guest_wlan, "choose_guest_wlan",
                              return_value={"id": "new-id", "ssid": "Guest-Events"}),
            mock.patch.object(setup_guest_wlan, "prompt_yes_no", return_value=False),
            mock.patch("builtins.print"),
            *extra_patches,
        ]
        for p in patches:
            p.start()
        try:
            setup_guest_wlan.main()
        finally:
            for p in reversed(patches):
                p.stop()

    def _assert_untouched(self):
        self.assertEqual(self.current.read_bytes(), PASSWORD)
        self.assertEqual(self.history.read_bytes(), HISTORY)
        self.assertEqual(self.env.read_text(encoding="utf-8"), ENV)


class WlanSwitchEnvWriteRollbackTests(_TmpDirCase):
    def test_env_write_error_restores_password_and_history(self):
        err = setup_guest_wlan.EnvWriteError(
            "could not write .env (denied). The new settings were kept in "
            "envwrite.1.tmp; rename it to .env once the file is writable.")
        with self.assertRaises(setup_guest_wlan.EnvWriteError) as cm:
            self._run_main(mock.patch.object(setup_guest_wlan, "upsert_env",
                                             side_effect=err))
        self.assertIs(cm.exception, err)
        self.assertIn("envwrite.", str(cm.exception))
        self._assert_untouched()
        self.assertNotIn(b"TARGET WLAN CHANGED", self.history.read_bytes())

    def test_other_oserror_from_env_write_restores_and_exits_1(self):
        with self.assertRaises(setup_guest_wlan.EnvWriteError):
            self._run_main(mock.patch.object(setup_guest_wlan, "upsert_env",
                                             side_effect=PermissionError(13, "denied")))
        self._assert_untouched()

    def test_non_oserror_failure_restores_and_reraises(self):
        with self.assertRaises(KeyboardInterrupt):
            self._run_main(mock.patch.object(setup_guest_wlan, "upsert_env",
                                             side_effect=KeyboardInterrupt))
        self._assert_untouched()

    def test_history_append_failure_after_env_saved_is_env_write_error(self):
        real_open = setup_guest_wlan.os.open

        def fake_open(path, *a, **kw):
            if Path(path) == self.history:
                raise OSError(28, "No space left on device")
            return real_open(path, *a, **kw)

        with self.assertRaises(setup_guest_wlan.EnvWriteError) as cm:
            self._run_main(mock.patch.object(setup_guest_wlan.os, "open", fake_open))
        self.assertIn("was saved", str(cm.exception))
        self.assertIn("MIST_WLAN_ID=new-id", self.env.read_text(encoding="utf-8"))
        self.assertTrue(self.current.read_text(encoding="utf-8").startswith("STALE"))
        self.assertEqual(self.history.read_bytes(), HISTORY)

    def test_marker_appended_only_after_env_saved(self):
        seen = {}
        real_upsert = setup_guest_wlan.upsert_env

        def spy(updates):
            seen["history"] = self.history.read_bytes()
            seen["current"] = self.current.read_text(encoding="utf-8")
            real_upsert(updates)

        self._run_main(mock.patch.object(setup_guest_wlan, "upsert_env", spy))
        self.assertEqual(seen["history"], HISTORY)
        self.assertTrue(seen["current"].startswith("STALE"))
        self.assertIn("MIST_WLAN_ID=new-id", self.env.read_text(encoding="utf-8"))
        last = self.history.read_text(encoding="utf-8").splitlines()[-1]
        self.assertIn("TARGET WLAN CHANGED", last)
        self.assertEqual(sorted(p.name for p in self.dir.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
