import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import setup_guest_wlan  # noqa: E402


@unittest.skipIf(os.name == "nt", "chmod failures are ignored on Windows")
class ChmodAfterReplaceTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.dest = self.dir / ".env"
        self.dest.write_text("OLD=1\n", encoding="utf-8")
        self.new = "MIST_API_TOKEN=new\n"
        real_chmod = os.chmod

        def chmod(path, mode, *a, **kw):
            if Path(path) == self.dest:
                raise PermissionError(1, "Operation not permitted", str(path))
            return real_chmod(path, mode, *a, **kw)

        p = mock.patch.object(setup_guest_wlan.os, "chmod", side_effect=chmod)
        p.start()
        self.addCleanup(p.stop)

    def _write_expect_error(self, replace):
        with mock.patch.object(setup_guest_wlan.os, "replace",
                               side_effect=replace) as rep:
            with self.assertRaises(setup_guest_wlan.EnvWriteError) as cm:
                setup_guest_wlan._atomic_write_text(self.dest, self.new)
        return str(cm.exception), rep

    def _assert_honest(self, msg):
        self.assertEqual(self.dest.read_text(encoding="utf-8"), self.new)
        self.assertNotIn("No such file", msg)
        self.assertNotIn("kept in", msg)
        self.assertNotIn("envwrite.", msg)
        self.assertIn("already has the new contents", msg)
        self.assertIn("mode", msg)
        self.assertEqual(list(self.dir.glob("*.tmp")), [])

    def test_first_replace_then_chmod_failure(self):
        msg, rep = self._write_expect_error(os.replace)
        self.assertEqual(rep.call_count, 1)
        self._assert_honest(msg)

    def test_second_replace_then_chmod_failure(self):
        real_replace = os.replace
        calls = []

        def replace(src, dst):
            calls.append(src)
            if len(calls) == 1:
                raise PermissionError(13, "Permission denied", str(dst))
            return real_replace(src, dst)

        msg, rep = self._write_expect_error(replace)
        self.assertEqual(rep.call_count, 2)
        self._assert_honest(msg)

    def test_replace_failure_still_names_temp(self):
        def replace(src, dst):
            raise OSError(5, "Input/output error", str(dst))

        msg, _ = self._write_expect_error(replace)
        self.assertIn("kept in", msg)
        self.assertEqual(self.dest.read_text(encoding="utf-8"), "OLD=1\n")


if __name__ == "__main__":
    unittest.main()
