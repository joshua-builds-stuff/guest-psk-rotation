import http.client
import os
import subprocess
import sys
import textwrap
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import rotate_guest_password  # noqa: E402
import setup_guest_wlan  # noqa: E402


class _BrokenBody:
    def __init__(self, exc):
        self._exc = exc

    def read(self, *a):
        raise self._exc

    def close(self):
        pass


def _http_error(exc, code=503):
    return urllib.error.HTTPError(
        "https://api.mist.com/api/v1/x", code, "Service Unavailable", {},
        _BrokenBody(exc))


class HttpErrorBodyReadTests(unittest.TestCase):
    MODULES = (rotate_guest_password, setup_guest_wlan)
    READ_ERRORS = (
        lambda: http.client.IncompleteRead(b"partial SECRET", 100),
        lambda: ConnectionResetError(104, "Connection reset by peer"),
    )

    def test_body_read_failure_becomes_runtime_error(self):
        for mod in self.MODULES:
            for make_exc in self.READ_ERRORS:
                exc = make_exc()
                with self.subTest(module=mod.__name__, exc=type(exc).__name__):
                    with mock.patch.object(mod.urllib.request, "urlopen",
                                           side_effect=_http_error(exc)):
                        with self.assertRaises(RuntimeError) as ctx:
                            mod.mist_request("GET", "https://api.mist.com",
                                             "SECRET-TOKEN", "/x")
                    msg = str(ctx.exception)
                    self.assertIn("Connection error reaching Mist API", msg)
                    self.assertIn(type(exc).__name__, msg)
                    self.assertNotIn("SECRET-TOKEN", msg)


class RotateExitCodeTests(unittest.TestCase):
    def _run(self, exc_expr):
        env_file = REPO / "tests" / "_tmp_issue23.env"
        env_file.write_text(textwrap.dedent("""\
            MIST_API_URL=https://api.mist.com
            MIST_API_TOKEN=SECRET-TOKEN
            MIST_ORG_ID=org
            MIST_WLAN_ID=wlan
        """))
        self.addCleanup(lambda: env_file.unlink(missing_ok=True))
        driver = textwrap.dedent(f"""
            import http.client, runpy, sys, urllib.error, urllib.request
            class B:
                def read(self, *a): raise {exc_expr}
                def close(self): pass
            def boom(*a, **k):
                raise urllib.error.HTTPError("u", 503, "x", {{}}, B())
            urllib.request.urlopen = boom
            sys.argv = ["rotate_guest_password.py", "--env", {str(env_file)!r}, "--dry-run"]
            runpy.run_path({str(REPO / "rotate_guest_password.py")!r}, run_name="__main__")
        """)
        return subprocess.run([sys.executable, "-c", driver], capture_output=True,
                              text=True, cwd=REPO, env={**os.environ})

    def test_exits_3_without_traceback(self):
        for expr in ("http.client.IncompleteRead(b'', 10)",
                     "ConnectionResetError(104, 'reset')"):
            with self.subTest(exc=expr):
                proc = self._run(expr)
                self.assertEqual(proc.returncode, 3, proc.stderr)
                self.assertNotIn("Traceback", proc.stderr)
                self.assertIn("ERROR", proc.stderr)
                self.assertNotIn("SECRET-TOKEN", proc.stderr)
                self.assertNotIn("SECRET-TOKEN", proc.stdout)


if __name__ == "__main__":
    unittest.main()
