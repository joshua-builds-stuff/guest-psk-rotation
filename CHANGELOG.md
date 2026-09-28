# Changelog

User-facing changes. Install steps, Python version, and `.env` keys are
unchanged unless an entry says otherwise.

## 2026-09-28

**Revision: minor**

### Fixed

- A Mist HTTP success response with a non-empty body that is not JSON (an
  HTML page, or bytes that are not valid UTF-8) is a Mist API error.
  `rotate_guest_password.py` prints one `ERROR:` line to stderr and exits
  **3**, including on `--dry-run`. There is no Python traceback, and the
  response body is not included. `setup_guest_wlan.py` uses the same
  sentence: `Validation failed: ...` while checking credentials (you can
  retry; answering no exits **1**), and `ERROR: ...` with exit **3** on
  later steps. Previously this case printed a traceback and exited **1**.
  Shipped in [#18](https://github.com/joshua-builds-stuff/guest-psk-rotation/pull/18)
  ([#17](https://github.com/joshua-builds-stuff/guest-psk-rotation/issues/17)).
  An HTTP error response that is not JSON is unchanged.
