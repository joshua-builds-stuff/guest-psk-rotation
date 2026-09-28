import io
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

HTML_BODY = b"<html>gateway error SECRET-TOKEN-XYZ</html>"


class _FakeResponse:
    def __init__(self, body, code=200):
        self._body = body
        self._code = code

    def read(self):
        return self._body

    def getcode(self):
        return self._code

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _http_error(body, code=502):
    return urllib.error.HTTPError(
        "https://api.mist.com/api/v1/x", code, "Bad Gateway", {}, io.BytesIO(body))


class MistRequestNonJsonTests(unittest.TestCase):
    MODULES = (rotate_guest_password, setup_guest_wlan)

    def test_non_json_200_raises_runtime_error_without_body(self):
        for mod in self.MODULES:
            with self.subTest(module=mod.__name__):
                with mock.patch.object(mod.urllib.request, "urlopen",
                                       return_value=_FakeResponse(HTML_BODY)):
                    with self.assertRaises(RuntimeError) as ctx:
                        mod.mist_request("GET", "https://api.mist.com", "tok", "/orgs/o")
                msg = str(ctx.exception)
                self.assertIn("non-JSON", msg)
                self.assertNotIn("SECRET-TOKEN-XYZ", msg)
                self.assertNotIn("<html>", msg)

    def test_non_utf8_200_raises_runtime_error(self):
        for mod in self.MODULES:
            with self.subTest(module=mod.__name__):
                with mock.patch.object(mod.urllib.request, "urlopen",
                                       return_value=_FakeResponse(b"\xff\xfe\x00garbage")):
                    with self.assertRaises(RuntimeError):
                        mod.mist_request("GET", "https://api.mist.com", "tok", "/orgs/o")

    def test_valid_json_and_empty_200_still_parse(self):
        for mod in self.MODULES:
            with self.subTest(module=mod.__name__):
                with mock.patch.object(mod.urllib.request, "urlopen",
                                       return_value=_FakeResponse(b'{"a": 1}')):
                    self.assertEqual(
                        mod.mist_request("GET", "https://api.mist.com", "tok", "/x"),
                        (200, {"a": 1}))
                with mock.patch.object(mod.urllib.request, "urlopen",
                                       return_value=_FakeResponse(b"")):
                    self.assertEqual(
                        mod.mist_request("GET", "https://api.mist.com", "tok", "/x"),
                        (200, None))

    def test_non_json_http_error_does_not_raise_decode_error(self):
        for mod in self.MODULES:
            with self.subTest(module=mod.__name__):
                with mock.patch.object(mod.urllib.request, "urlopen",
                                       side_effect=_http_error(HTML_BODY)):
                    status, _detail = mod.mist_request(
                        "GET", "https://api.mist.com", "tok", "/x")
                self.assertEqual(status, 502)


class RotateExitCodeTests(unittest.TestCase):
    def test_non_json_200_exits_3_not_1(self):
        env_file = REPO / "tests" / "_tmp_issue17.env"
        env_file.write_text(textwrap.dedent("""\
            MIST_API_URL=https://api.mist.com
            MIST_API_TOKEN=tok
            MIST_ORG_ID=org
            MIST_WLAN_ID=wlan
        """))
        self.addCleanup(lambda: env_file.unlink(missing_ok=True))
        driver = textwrap.dedent(f"""
            import runpy, sys, urllib.request
            class R:
                def read(self): return {HTML_BODY!r}
                def getcode(self): return 200
                def __enter__(self): return self
                def __exit__(self, *a): return False
            urllib.request.urlopen = lambda *a, **k: R()
            sys.argv = ["rotate_guest_password.py", "--env", {str(env_file)!r}, "--dry-run"]
            runpy.run_path({str(REPO / "rotate_guest_password.py")!r}, run_name="__main__")
        """)
        proc = subprocess.run([sys.executable, "-c", driver], capture_output=True,
                              text=True, cwd=REPO, env={**os.environ})
        self.assertEqual(proc.returncode, 3, proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertNotIn("SECRET-TOKEN-XYZ", proc.stderr)


if __name__ == "__main__":
    unittest.main()
