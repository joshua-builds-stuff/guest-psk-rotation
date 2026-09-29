import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import rotate_guest_password  # noqa: E402
import setup_guest_wlan  # noqa: E402


class _TmpDirCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.current = self.dir / "current_password.txt"
        self.history = self.dir / "password_history.log"
        self.env = self.dir / ".env"
        for mod in (setup_guest_wlan, rotate_guest_password):
            p1 = mock.patch.object(mod, "CURRENT_PASSWORD_FILE", self.current)
            p2 = mock.patch.object(mod, "HISTORY_LOG", self.history)
            p1.start()
            p2.start()
            self.addCleanup(p1.stop)
            self.addCleanup(p2.stop)
        p3 = mock.patch.object(setup_guest_wlan, "ENV_PATH", self.env)
        p3.start()
        self.addCleanup(p3.stop)
        p4 = mock.patch.object(setup_guest_wlan, "LOCK_FILE", self.dir / "rotate.lock")
        p4.start()
        self.addCleanup(p4.stop)
        self.addCleanup(self._tmp.cleanup)


class InvalidateOnWlanChangeTests(_TmpDirCase):
    def _seed(self):
        self.current.write_text("apples\n", encoding="utf-8")
        self.history.write_text("2026-01-01 06:00:00\tGuest-WiFi\tapples\n",
                                encoding="utf-8")

    def test_changed_wlan_marks_password_stale(self):
        self._seed()
        changed = setup_guest_wlan.invalidate_published_password(
            "old-id", "Guest-WiFi", "new-id", "Guest-Events")
        self.assertTrue(changed)
        text = self.current.read_text(encoding="utf-8")
        self.assertNotIn("apples", text)
        self.assertTrue(text.startswith("STALE"))
        self.assertIn("Guest-WiFi", text)
        self.assertIn("Guest-Events", text)
        last = self.history.read_text(encoding="utf-8").splitlines()[-1]
        self.assertIn("TARGET WLAN CHANGED", last)
        self.assertIn("Guest-Events", last)
        self.assertEqual(list(self.dir.glob("*.tmp")), [])

    def test_same_wlan_leaves_files_alone(self):
        self._seed()
        changed = setup_guest_wlan.invalidate_published_password(
            "same", "Guest-WiFi", "same", "Guest-WiFi")
        self.assertFalse(changed)
        self.assertEqual(self.current.read_text(encoding="utf-8"), "apples\n")
        self.assertEqual(len(self.history.read_text().splitlines()), 1)

    def test_first_setup_creates_nothing(self):
        changed = setup_guest_wlan.invalidate_published_password(
            "", "", "new-id", "Guest")
        self.assertFalse(changed)
        self.assertFalse(self.current.exists())
        self.assertFalse(self.history.exists())

    def test_main_invalidates_before_saving_new_wlan(self):
        self._seed()
        self.env.write_text(
            "MIST_API_TOKEN=t\nMIST_WLAN_ID=old-id\nMIST_WLAN_SSID=Guest-WiFi\n",
            encoding="utf-8")
        cfg = {"api_url": "https://api.mist.com", "token": "t", "org_id": "o",
               "org_name": "Org"}
        with mock.patch.object(setup_guest_wlan, "collect_and_store_credentials",
                               return_value=cfg), \
                mock.patch.object(setup_guest_wlan, "choose_template",
                                  return_value={"id": "tmpl", "name": "T"}), \
                mock.patch.object(setup_guest_wlan, "choose_guest_wlan",
                                  return_value={"id": "new-id", "ssid": "Guest-Events"}), \
                mock.patch.object(setup_guest_wlan, "prompt_yes_no", return_value=False), \
                mock.patch("builtins.print"):
            setup_guest_wlan.main()
        self.assertTrue(self.current.read_text().startswith("STALE"))
        env = self.env.read_text()
        self.assertIn("MIST_WLAN_ID=new-id", env)
        self.assertIn("MIST_API_TOKEN=t", env)


class RecordNewPasswordTests(_TmpDirCase):
    def test_current_password_is_self_describing(self):
        rotate_guest_password.record_new_password("Guest-Events", "rainbow", "new-id")
        lines = self.current.read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines[0], "rainbow")
        self.assertIn("# SSID: Guest-Events", lines)
        self.assertIn("# WLAN ID: new-id", lines)


if __name__ == "__main__":
    unittest.main()
