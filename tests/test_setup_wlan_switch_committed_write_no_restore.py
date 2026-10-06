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


class CommittedWriteNoRestoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
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
        self.current.write_bytes(PASSWORD)
        self.history.write_bytes(HISTORY)
        self.env.write_text(ENV, encoding="utf-8")

    def _chmod_fails_for(self, target):
        real_chmod = setup_guest_wlan.os.chmod

        def fake_chmod(path, mode, *a, **kw):
            if Path(path) == target:
                raise PermissionError(1, "Operation not permitted")
            return real_chmod(path, mode, *a, **kw)

        return mock.patch.object(setup_guest_wlan.os, "chmod", fake_chmod)

    def _save(self):
        setup_guest_wlan.upsert_env({"MIST_WLAN_ID": "new-id",
                                     "MIST_WLAN_SSID": "Guest-Events"})

    def _invalidate(self, save):
        return setup_guest_wlan.invalidate_published_password(
            "old-id", "Guest-WiFi", "new-id", "Guest-Events", save=save)

    def test_env_chmod_failure_after_replace_keeps_stale_and_marks_history(self):
        with self._chmod_fails_for(self.env):
            with self.assertRaises(setup_guest_wlan.EnvWriteError) as cm:
                self._invalidate(self._save)
        self.assertTrue(cm.exception.contents_committed)
        msg = str(cm.exception)
        self.assertIn(str(self.env), msg)
        self.assertIn("already has the new contents", msg)
        self.assertIn("Only the mode change failed", msg)
        self.assertIn("MIST_WLAN_ID=new-id", self.env.read_text(encoding="utf-8"))
        self.assertTrue(self.current.read_text(encoding="utf-8").startswith("STALE"))
        self.assertIn(b"TARGET WLAN CHANGED", self.history.read_bytes())

    def test_env_chmod_failure_exits_1_from_main(self):
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
            self._chmod_fails_for(self.env),
        ]
        for p in patches:
            p.start()
        try:
            with self.assertRaises(setup_guest_wlan.EnvWriteError) as cm:
                setup_guest_wlan.main()
        finally:
            for p in reversed(patches):
                p.stop()
        self.assertTrue(cm.exception.contents_committed)
        self.assertIn("MIST_WLAN_ID=new-id", self.env.read_text(encoding="utf-8"))
        self.assertTrue(self.current.read_text(encoding="utf-8").startswith("STALE"))
        last = self.history.read_text(encoding="utf-8").splitlines()[-1]
        self.assertIn("TARGET WLAN CHANGED", last)

    def test_stale_chmod_failure_does_not_restore_and_still_saves(self):
        calls = []

        def save():
            calls.append(self.current.read_text(encoding="utf-8"))
            self._save()

        with self._chmod_fails_for(self.current):
            with self.assertRaises(setup_guest_wlan.EnvWriteError) as cm:
                self._invalidate(save)
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0].startswith("STALE"))
        self.assertTrue(cm.exception.contents_committed)
        self.assertIn(str(self.current), str(cm.exception))
        self.assertTrue(self.current.read_text(encoding="utf-8").startswith("STALE"))
        self.assertIn("MIST_WLAN_ID=new-id", self.env.read_text(encoding="utf-8"))
        self.assertIn(b"TARGET WLAN CHANGED", self.history.read_bytes())

    def test_pre_replace_env_write_failure_still_restores(self):
        real_replace = setup_guest_wlan.os.replace

        def fake_replace(src, dst, *a, **kw):
            if Path(dst) == self.env:
                raise OSError(28, "No space left on device")
            return real_replace(src, dst, *a, **kw)

        with mock.patch.object(setup_guest_wlan.os, "replace", fake_replace):
            with self.assertRaises(setup_guest_wlan.EnvWriteError) as cm:
                self._invalidate(self._save)
        self.assertFalse(cm.exception.contents_committed)
        self.assertEqual(self.current.read_bytes(), PASSWORD)
        self.assertEqual(self.env.read_text(encoding="utf-8"), ENV)
        self.assertEqual(self.history.read_bytes(), HISTORY)
        for tmp in self.dir.glob("envwrite.*.tmp"):
            tmp.unlink()


if __name__ == "__main__":
    unittest.main()
