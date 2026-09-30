# Changelog

User-facing changes. Install steps, Python version, and `.env` keys are
unchanged unless an entry says otherwise.

## 2026-09-28

**Revision: minor**

### Fixed

- `rotate_guest_password.py` prints and flushes the SSID and new password
  as soon as the password PUT returns HTTP 200 with a JSON object, before
  the confirming GET and before local password files are written.
  `current_password.txt` is replaced via a temp file, `fsync`, and
  `os.replace` (password on line 1, then SSID, WLAN id, and time). If a
  local write fails after that publish, the process exits **1** and the
  error repeats the password Mist is using. Stdout already has the same
  word.
  [#11](https://github.com/joshua-builds-stuff/guest-psk-rotation/pull/11)
  ([#2](https://github.com/joshua-builds-stuff/guest-psk-rotation/issues/2)).

- `setup_guest_wlan.py` lists every page of org templates and WLANs
  (`mist_get_all`, `limit=1000`, `page`, stop on a short page or
  `X-Page-Total`). A page that is not HTTP 200 with a list exits **3**.
  [#12](https://github.com/joshua-builds-stuff/guest-psk-rotation/pull/12)
  ([#3](https://github.com/joshua-builds-stuff/guest-psk-rotation/issues/3)).

- Setup never deletes `.env` before the replacement is written. It `fsync`s
  `envwrite.<pid>.tmp` and `os.replace`s it into place. There is no
  delete-then-rename fallback. If replace fails, it clears a Windows hidden
  attribute when it can and then overwrites the existing file in place. A
  failed write exits **1** and names the temp file, which still holds the
  new settings.
  [#13](https://github.com/joshua-builds-stuff/guest-psk-rotation/pull/13)
  ([#4](https://github.com/joshua-builds-stuff/guest-psk-rotation/issues/4)).

- A real rotation holds an exclusive non-blocking lock on `rotate.lock`
  (`fcntl.flock` on POSIX, `msvcrt.locking` on Windows) until the process
  exits. A second rotation exits **1** and does not call Mist. `--dry-run`
  does not take the lock.
  [#14](https://github.com/joshua-builds-stuff/guest-psk-rotation/pull/14)
  ([#5](https://github.com/joshua-builds-stuff/guest-psk-rotation/issues/5)).

- Password rotation PUTs only `{"portal": ...}` (the portal object from the
  GET, with the new password) and confirms with a fresh GET of the WLAN.
  [#15](https://github.com/joshua-builds-stuff/guest-psk-rotation/pull/15)
  ([#6](https://github.com/joshua-builds-stuff/guest-psk-rotation/issues/6)).

- A Mist API timeout (30 seconds) in either script becomes a `RuntimeError`
  and exit **3**: one `ERROR:` line, no traceback. Other `OSError` and
  `http.client` failures during the call use that same exit **3** path.
  [#16](https://github.com/joshua-builds-stuff/guest-psk-rotation/pull/16)
  ([#7](https://github.com/joshua-builds-stuff/guest-psk-rotation/issues/7)).

- While setup re-checks the chosen SSID, HTTP errors are reported as Mist
  API errors. **401** and **403** exit **3** (token rejected). **404**
  returns to the SSID list. **429**, **5xx**, and other HTTP errors print
  the status and offer a retry; declining exits **3**. A GET that succeeds
  with `portal.auth` other than `password` still asks you to pick another
  SSID.
  [#19](https://github.com/joshua-builds-stuff/guest-psk-rotation/pull/19)
  ([#8](https://github.com/joshua-builds-stuff/guest-psk-rotation/issues/8)).

- If setup saves a different WLAN than `MIST_WLAN_ID` already in `.env`, it
  replaces `current_password.txt` with a `STALE` notice when that file
  exists, and appends a `TARGET WLAN CHANGED` line to `password_history.log`
  when that file exists, before `.env` is updated. The same WLAN leaves
  both files unchanged. A first setup does not create them.
  [#20](https://github.com/joshua-builds-stuff/guest-psk-rotation/pull/20)
  ([#9](https://github.com/joshua-builds-stuff/guest-psk-rotation/issues/9)).

Python 3.8+, no `pip` install, and the `.env` keys are unchanged.

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

- `setup_guest_wlan.py` takes the same `rotate.lock` as a rotation while it
  writes the `STALE` notice and saves the WLAN id to `.env`. If a rotation
  holds the lock, setup prints `ERROR: A rotation is running ... Setup did
  not save the new WLAN` and exits **1** without that write. A rotation
  re-reads `.env` after taking the lock and exits **1** without a PUT if
  `MIST_WLAN_ID` changed.
  [#28](https://github.com/joshua-builds-stuff/guest-psk-rotation/pull/28)
  ([#24](https://github.com/joshua-builds-stuff/guest-psk-rotation/issues/24)).

## 2026-09-30

**Revision: minor**

### Fixed

- `setup_guest_wlan.py` no longer writes Mist credentials when the step-1
  org check succeeds. `MIST_API_URL`, `MIST_API_TOKEN`, and `MIST_ORG_ID`
  are saved in the same `rotate.lock` write as `MIST_WLAN_ID`,
  `MIST_WLAN_TEMPLATE_ID`, `MIST_WLAN_SSID`, and `MIST_BACKUP_JSON`. If
  setup exits before that write, the new token is not stored and any
  previous `.env` is left as it was. That includes declining `Try again?`
  (exit **1**), a later step exiting **3**, Ctrl-C, and a rotation holding
  `rotate.lock` (exit **1**; the STALE notice is not written either). The
  lock rules are unchanged: exclusive and non-blocking, not taken on
  `--dry-run`, and a busy lock still exits **1** with no Mist call from a
  second rotation.
  [#31](https://github.com/joshua-builds-stuff/guest-psk-rotation/pull/31)
  ([#29](https://github.com/joshua-builds-stuff/guest-psk-rotation/issues/29)).

Python 3.8+, no `pip` install, and the `.env` key names are unchanged.
