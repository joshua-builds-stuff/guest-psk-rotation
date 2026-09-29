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

import rotate_guest_password  # noqa: E402
import setup_guest_wlan  # noqa: E402

ENV_TEMPLATE = ("MIST_API_URL=https://api.mist.com\nMIST_API_TOKEN=SECRET-TOKEN-XYZ\n"
                "MIST_ORG_ID=org\nMIST_WLAN_ID={wlan_id}\nMIST_WLAN_SSID=Guest-WiFi\n")


def _try_flock(path):
    """Return True if an exclusive lock on path can be taken right now."""
    import fcntl
    with open(path, "a+", encoding="utf-8") as f:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        return True


class _TmpDirCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.current = self.dir / "current_password.txt"
        self.history = self.dir / "password_history.log"
        self.env = self.dir / ".env"
        self.lock = self.dir / "rotate.lock"
        self.current.write_text("apples\n", encoding="utf-8")
        self.env.write_text(ENV_TEMPLATE.format(wlan_id="old-id"), encoding="utf-8")
        for mod in (setup_guest_wlan, rotate_guest_password):
            for name, val in (("CURRENT_PASSWORD_FILE", self.current),
                              ("HISTORY_LOG", self.history),
                              ("LOCK_FILE", self.lock)):
                p = mock.patch.object(mod, name, val)
                p.start()
                self.addCleanup(p.stop)
        p = mock.patch.object(setup_guest_wlan, "ENV_PATH", self.env)
        p.start()
        self.addCleanup(p.stop)

    def _run_setup(self):
        cfg = {"api_url": "https://api.mist.com", "token": "tok", "org_id": "org",
               "org_name": "Org"}
        with mock.patch.object(setup_guest_wlan, "collect_and_store_credentials",
                               return_value=cfg), \
                mock.patch.object(setup_guest_wlan, "choose_template",
                                  return_value={"id": "tmpl", "name": "T"}), \
                mock.patch.object(setup_guest_wlan, "choose_guest_wlan",
                                  return_value={"id": "new-id", "ssid": "Guest-Events"}), \
                mock.patch.object(setup_guest_wlan, "prompt_yes_no", return_value=False), \
                redirect_stdout(io.StringIO()):
            setup_guest_wlan.main()


@unittest.skipIf(os.name == "nt", "fcntl-based check")
class SetupHoldsLockTests(_TmpDirCase):
    def test_lock_held_during_stale_notice_and_env_write(self):
        seen = []
        real_invalidate = setup_guest_wlan.invalidate_published_password
        real_upsert = setup_guest_wlan.upsert_env

        def invalidate(*a):
            seen.append(("invalidate", _try_flock(self.lock)))
            return real_invalidate(*a)

        def upsert(updates):
            seen.append(("upsert", _try_flock(self.lock)))
            return real_upsert(updates)

        with mock.patch.object(setup_guest_wlan, "invalidate_published_password",
                               side_effect=invalidate), \
                mock.patch.object(setup_guest_wlan, "upsert_env", side_effect=upsert):
            self._run_setup()
        self.assertEqual(seen, [("invalidate", False), ("upsert", False)])
        self.assertTrue(_try_flock(self.lock), "setup must release the lock")
        self.assertIn("MIST_WLAN_ID=new-id", self.env.read_text())

    def test_setup_exits_1_without_writing_while_rotation_holds_lock(self):
        holder = rotate_guest_password.acquire_rotation_lock()
        self.addCleanup(holder.close)
        err = io.StringIO()
        with redirect_stderr(err), self.assertRaises(SystemExit) as ctx:
            self._run_setup()
        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("rotation is running", err.getvalue())
        self.assertEqual(self.current.read_text(), "apples\n")
        self.assertIn("MIST_WLAN_ID=old-id", self.env.read_text())


class RotationRereadsEnvAfterLockTests(_TmpDirCase):
    def _run_rotation(self, lock_side_effect):
        argv = ["rotate_guest_password.py", "--env", str(self.env)]
        err = io.StringIO()
        with mock.patch.object(sys, "argv", argv), \
                mock.patch.object(rotate_guest_password, "acquire_rotation_lock",
                                  side_effect=lock_side_effect), \
                mock.patch.object(rotate_guest_password, "mist_request",
                                  side_effect=AssertionError("Mist called")) as mr, \
                redirect_stderr(err), redirect_stdout(io.StringIO()):
            try:
                rotate_guest_password.main()
            except (SystemExit, AssertionError) as e:
                return e, mr, err.getvalue()
        return None, mr, err.getvalue()

    def test_wlan_id_changed_after_lock_aborts_without_put(self):
        def setup_ran_first():
            self.env.write_text(ENV_TEMPLATE.format(wlan_id="new-id"), encoding="utf-8")
            return io.StringIO()

        exc, mr, err = self._run_rotation(setup_ran_first)
        self.assertIsInstance(exc, SystemExit)
        self.assertEqual(exc.code, 1)
        mr.assert_not_called()
        self.assertIn("old-id", err)
        self.assertIn("new-id", err)
        self.assertNotIn("SECRET-TOKEN-XYZ", err)
        self.assertEqual(self.current.read_text(), "apples\n")
        self.assertFalse(self.history.exists())

    def test_unchanged_wlan_id_proceeds_to_mist(self):
        exc, mr, _ = self._run_rotation(lambda: io.StringIO())
        self.assertIsInstance(exc, AssertionError)
        mr.assert_called_once()
        self.assertIn("old-id", mr.call_args.args[3])


if __name__ == "__main__":
    unittest.main()
