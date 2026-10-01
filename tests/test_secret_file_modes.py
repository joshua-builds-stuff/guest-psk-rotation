import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import rotate_guest_password  # noqa: E402
import setup_guest_wlan  # noqa: E402


@unittest.skipIf(os.name == "nt", "Unix file modes are not Windows ACLs")
class SecretFileModeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.env = self.dir / ".env"
        self.current = self.dir / "current_password.txt"
        self.history = self.dir / "password_history.log"
        for module in (setup_guest_wlan, rotate_guest_password):
            for name, path in (("CURRENT_PASSWORD_FILE", self.current),
                               ("HISTORY_LOG", self.history)):
                patcher = mock.patch.object(module, name, path)
                patcher.start()
                self.addCleanup(patcher.stop)
        for module, name, path in (
                (setup_guest_wlan, "ENV_PATH", self.env),
                (rotate_guest_password, "BACKUP_DIR", self.dir / "backups")):
            patcher = mock.patch.object(module, name, path)
            patcher.start()
            self.addCleanup(patcher.stop)

    def assert_secret(self, path):
        self.assertEqual(path.stat().st_mode & 0o777, 0o600, str(path))

    def assert_atomic_temp_is_private(self, module, path, content):
        replace = os.replace

        def check_then_replace(src, dst):
            self.assert_secret(Path(src))
            return replace(src, dst)

        with mock.patch.object(module.os, "replace", side_effect=check_then_replace):
            module._atomic_write_text(path, content)
        self.assert_secret(path)

    def test_atomic_writers_create_private_temp_and_destination(self):
        self.assert_atomic_temp_is_private(setup_guest_wlan, self.env,
                                           "MIST_API_TOKEN=secret\n")
        self.assert_atomic_temp_is_private(rotate_guest_password, self.current,
                                           "password\n")

    def test_atomic_writers_tighten_existing_files_and_temp(self):
        for module, path in ((setup_guest_wlan, self.env),
                             (rotate_guest_password, self.current)):
            path.write_text("old\n", encoding="utf-8")
            path.chmod(0o644)
            temp = path.parent / (f"envwrite.{os.getpid()}.tmp" if
                                  module is setup_guest_wlan else
                                  f"{path.name}.{os.getpid()}.tmp")
            temp.write_text("old temp\n", encoding="utf-8")
            temp.chmod(0o644)
            self.assert_atomic_temp_is_private(module, path, "new\n")
            self.assertEqual(path.read_text(encoding="utf-8"), "new\n")

    def test_upsert_env_creates_and_tightens(self):
        setup_guest_wlan.upsert_env({"MIST_API_TOKEN": "first"})
        self.assert_secret(self.env)
        self.env.chmod(0o644)
        setup_guest_wlan.upsert_env({"MIST_API_TOKEN": "second"})
        self.assert_secret(self.env)
        self.assertIn("MIST_API_TOKEN=second", self.env.read_text())

    def test_setup_fallback_tightens_existing_destination(self):
        self.env.write_text("MIST_API_TOKEN=old\n", encoding="utf-8")
        self.env.chmod(0o644)
        with mock.patch.object(setup_guest_wlan.os, "replace",
                               side_effect=PermissionError("replace denied")):
            setup_guest_wlan._atomic_write_text(self.env, "MIST_API_TOKEN=new\n")
        self.assert_secret(self.env)
        self.assertEqual(self.env.read_text(), "MIST_API_TOKEN=new\n")

    def test_record_new_password_creates_and_tightens_history(self):
        rotate_guest_password.record_new_password("Guest", "first")
        self.assert_secret(self.current)
        self.assert_secret(self.history)
        self.current.chmod(0o644)
        self.history.chmod(0o644)
        rotate_guest_password.record_new_password("Guest", "second")
        self.assert_secret(self.current)
        self.assert_secret(self.history)
        self.assertEqual(len(self.history.read_text().splitlines()), 2)

    def test_setup_history_append_tightens_existing_log(self):
        self.history.write_text("old secret\n", encoding="utf-8")
        self.history.chmod(0o644)
        self.current.write_text("old password\n", encoding="utf-8")
        self.current.chmod(0o644)
        self.assertTrue(setup_guest_wlan.invalidate_published_password(
            "old", "Old", "new", "New"))
        self.assert_secret(self.history)
        self.assert_secret(self.current)
        self.assertIn("TARGET WLAN CHANGED", self.history.read_text())

    def test_backup_is_private(self):
        path = rotate_guest_password.save_backup(
            "Guest", {"portal": {"password": "secret"}})
        self.assert_secret(path)
        self.assertEqual(json.loads(path.read_text())["portal"]["password"],
                         "secret")


if __name__ == "__main__":
    unittest.main()
