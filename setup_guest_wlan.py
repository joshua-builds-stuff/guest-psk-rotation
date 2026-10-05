#!/usr/bin/env python3
"""
Guest WLAN Setup (Juniper Mist)
===============================

One-time interactive setup for the guest-password rotation tool.

Provided as is, without warranty of any kind; not an official Hewlett
Packard Enterprise (HPE) product and not supported by HPE or HPE Juniper
Networking (formerly Juniper Networks).

What it does:
  1. Collects your Mist Org ID, API Token, and cloud instance, validates
     them against the Mist API. Nothing is written to `.env` yet.
  2. Lists every Wireless LAN Template in the org; you pick one.
  3. Lists the SSIDs in that template (annotated with their portal auth
     type); you pick the guest SSID you want to manage.
  4. Validates via the API that the chosen SSID has a guest captive portal
     (portal.auth == "password" and portal.passphrase_enabled). If it does not, it says so and lets you
     pick again. If the API call itself fails, it reports the HTTP error
     instead (retry, or exit 3) rather than blaming the SSID.
  5. Asks whether to keep a JSON backup of the WLAN before each change.
  6. Records the credentials, WLAN ID, and your choices in `.env` in one
     write, under rotate.lock. If this replaces a
     previously configured WLAN, current_password.txt is marked stale and
     a marker is added to password_history.log.

After this runs once, rotate_guest_password.py can rotate the password
fully unattended (schedule it with Task Scheduler / cron).

Pure Python standard library only. The only network calls are to Mist.

A non-empty Mist success body that is not JSON is reported as an API
error. Credential checks show it as "Validation failed" and can be
retried (answering no exits 1). Later steps print one ERROR line and
exit 3, with no traceback. The response body is not included. See README.md.
"""

import http.client
import json
import os
import socket
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

SCRIPT_DIR = Path(__file__).resolve().parent
ENV_PATH = SCRIPT_DIR / ".env"
CURRENT_PASSWORD_FILE = SCRIPT_DIR / "current_password.txt"
HISTORY_LOG = SCRIPT_DIR / "password_history.log"
LOCK_FILE = SCRIPT_DIR / "rotate.lock"
API_TIMEOUT = 30
PAGE_LIMIT = 1000  # Mist's documented maximum page size

# The 12 Mist regional clouds (matches your standard env_handler convention).
CLOUD_ENDPOINTS = {
    "1":  ("Global 01", "https://api.mist.com"),
    "2":  ("Global 02", "https://api.gc1.mist.com"),
    "3":  ("Global 03", "https://api.ac2.mist.com"),
    "4":  ("Global 04", "https://api.gc2.mist.com"),
    "5":  ("Global 05", "https://api.gc4.mist.com"),
    "6":  ("EMEA 01",   "https://api.eu.mist.com"),
    "7":  ("EMEA 02",   "https://api.gc3.mist.com"),
    "8":  ("EMEA 03",   "https://api.ac6.mist.com"),
    "9":  ("EMEA 04",   "https://api.gc6.mist.com"),
    "10": ("APAC 01",   "https://api.ac5.mist.com"),
    "11": ("APAC 02",   "https://api.gc5.mist.com"),
    "12": ("APAC 03",   "https://api.gc7.mist.com"),
}
_ALLOWED_HOSTS = frozenset(urlparse(url).hostname for _, url in CLOUD_ENDPOINTS.values())


# --------------------------------------------------------------------------- #
# Mist API (stdlib urllib only)
# --------------------------------------------------------------------------- #

def mist_request(method, api_url, token, path, body=None, with_headers=False):
    """Perform a Mist API request. Returns (status_code, parsed_json_or_text).

    With with_headers=True, returns (status_code, body, headers).
    """
    url = f"{api_url.rstrip('/')}/api/v1{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Token {token}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=API_TIMEOUT) as resp:
            raw = resp.read()
            try:
                parsed = json.loads(raw) if raw else None
            except ValueError:
                raise RuntimeError(
                    f"Mist API returned a non-JSON response (HTTP {resp.getcode()}) "
                    f"for {method} {path}.") from None
            result = (resp.getcode(), parsed)
            headers = resp.headers if with_headers else None
    except urllib.error.HTTPError as e:
        try:
            raw = e.read()
        except (OSError, http.client.HTTPException) as read_err:
            raise RuntimeError(
                f"Connection error reaching Mist API: "
                f"{type(read_err).__name__}: {read_err}") from None
        try:
            detail = json.loads(raw)
        except Exception:
            detail = raw.decode("utf-8", errors="replace")[:300]
        result, headers = (e.code, detail), e.headers
    except urllib.error.URLError as e:
        raise RuntimeError(f"Connection error reaching Mist API: {e.reason}")
    except (TimeoutError, socket.timeout):
        raise RuntimeError(
            f"Timed out after {API_TIMEOUT}s waiting for the Mist API to respond.")
    except (OSError, http.client.HTTPException) as e:
        raise RuntimeError(
            f"Connection error reaching Mist API: {type(e).__name__}: {e}")
    return (*result, headers) if with_headers else result


def mist_get_all(cfg, path, what):
    """GET every page of a Mist list endpoint. Exits 3 if any page fails."""
    items, page = [], 1
    while True:
        status, body, headers = mist_request(
            "GET", cfg["api_url"], cfg["token"],
            f"{path}?limit={PAGE_LIMIT}&page={page}", with_headers=True)
        if status != 200 or not isinstance(body, list):
            print(f"ERROR: could not list {what} (HTTP {status}, page {page}).",
                  file=sys.stderr)
            sys.exit(3)
        items.extend(body)
        try:
            total = int((headers or {}).get("X-Page-Total", ""))
        except ValueError:
            total = None
        if len(body) < PAGE_LIMIT or (total is not None and page * PAGE_LIMIT >= total):
            return items
        page += 1


def validate_credentials(api_url, token, org_id):
    """Return (ok, org_name_or_error) for the given credentials."""
    if (urlparse(api_url).hostname or "") not in _ALLOWED_HOSTS:
        return False, "Unrecognized Mist cloud URL"
    try:
        status, body = mist_request("GET", api_url, token, f"/orgs/{org_id}")
    except RuntimeError as e:
        return False, str(e)
    if status == 200 and isinstance(body, dict):
        return True, body.get("name", "Unknown")
    if status == 401:
        return False, "Authentication failed (invalid token)"
    if status == 403:
        return False, "Permission denied for this token"
    if status == 404:
        return False, "Organization not found (invalid org ID)"
    return False, f"API returned status {status}"


# --------------------------------------------------------------------------- #
# .env read / write
# --------------------------------------------------------------------------- #

class EnvWriteError(Exception):
    """.env could not be written; the message names the preserved temp file."""


def _clear_hidden(path: Path) -> None:
    """Best-effort removal of the Windows hidden/system attribute (no-op elsewhere)."""
    if os.name != "nt":
        return
    try:
        import ctypes
        FILE_ATTRIBUTE_NORMAL = 0x80
        ctypes.windll.kernel32.SetFileAttributesW(str(path), FILE_ATTRIBUTE_NORMAL)
    except Exception:
        pass


def _chmod_secret(path: Path) -> None:
    """Restrict an existing secret file (best effort on Windows)."""
    try:
        os.chmod(path, 0o600)
    except OSError:
        if os.name != "nt":
            raise


def _atomic_write_text(path: Path, content: str) -> None:
    """Write text to `path` atomically and robustly.

    Writes to a temp file (with a normal, non-dot name) then os.replace()s it
    into place. This is crash-safe AND sidesteps a Windows quirk: dotfiles on a
    Samba/SMB share are shown as 'hidden', and opening an existing hidden file
    with mode 'w' raises PermissionError. os.replace can overwrite a hidden
    target; if it can't, clear the attribute and retry, then fall back to
    overwriting the existing file in place (mode 'r+' opens hidden files).

    The destination is never deleted. The temp file is removed only after the
    new content is in place; on failure it is kept and EnvWriteError names it
    so the credentials can be recovered.
    """
    tmp = path.parent / f"envwrite.{os.getpid()}.tmp"
    with os.fdopen(os.open(tmp, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600),
                   "w", encoding="utf-8") as f:
        _chmod_secret(tmp)
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
    try:
        try:
            os.replace(tmp, path)
            _chmod_secret(path)
            return
        except PermissionError:
            pass
        _clear_hidden(path)
        try:
            os.replace(tmp, path)
            _chmod_secret(path)
            return
        except PermissionError:
            if not path.exists():
                raise
        _chmod_secret(path)
        with open(path, "r+", encoding="utf-8") as f:
            f.seek(0)
            f.write(content)
            f.truncate()
            f.flush()
            os.fsync(f.fileno())
        _chmod_secret(path)
    except OSError as e:
        raise EnvWriteError(
            f"could not write {path} ({e}). The new settings were kept in "
            f"{tmp}; rename it to {path.name} once the file is writable.") from e
    try:
        tmp.unlink()
    except OSError:
        pass


def read_env() -> dict:
    """Return the KEY=VALUE pairs currently in .env (empty if missing)."""
    env = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                key, value = stripped.split("=", 1)
                env[key.strip()] = value.strip()
    return env


def _restore_published_password(previous: bytes, cause: BaseException) -> None:
    """Put back the previous current_password.txt bytes after a failed switch."""
    try:
        if CURRENT_PASSWORD_FILE.read_bytes() == previous:
            return
    except OSError:
        pass
    tmp = CURRENT_PASSWORD_FILE.parent / f"pwrestore.{os.getpid()}.tmp"
    try:
        with os.fdopen(os.open(tmp, os.O_CREAT | os.O_WRONLY | os.O_TRUNC
                               | getattr(os, "O_BINARY", 0), 0o600), "wb") as f:
            f.write(previous)
            f.flush()
            os.fsync(f.fileno())
    except OSError as e:
        raise EnvWriteError(
            f"setup failed ({cause}) and {CURRENT_PASSWORD_FILE} could not be "
            f"restored ({e}). It may say STALE, but .env still names the "
            f"previous WLAN and its password is unchanged in Mist.") from e
    try:
        os.replace(tmp, CURRENT_PASSWORD_FILE)
    except OSError as e:
        raise EnvWriteError(
            f"setup failed ({cause}) and {CURRENT_PASSWORD_FILE} could not be "
            f"restored ({e}). .env still names the previous WLAN; the previous "
            f"password file was kept in {tmp}; rename it to "
            f"{CURRENT_PASSWORD_FILE.name}.") from e


def invalidate_published_password(old_id: str, old_ssid: str,
                                  new_id: str, new_ssid: str,
                                  save=None) -> bool:
    """Mark the published password stale after the target WLAN changes.

    current_password.txt still holds the previous WLAN's password until the
    new WLAN is rotated, so replace it with a notice and add a marker to the
    history log. Returns True if anything was changed.

    If `save` is given it is called after the notice is written and before
    the marker is added. If it fails, current_password.txt is restored, the
    history log is left alone, and the error is raised (OSError as
    EnvWriteError). A failed marker append after `save` succeeded raises
    EnvWriteError.
    """
    if not old_id or old_id == new_id:
        if save is not None:
            save()
        return False
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    old_label = f"'{old_ssid}' ({old_id})" if old_ssid else old_id
    new_label = f"'{new_ssid}' ({new_id})" if new_ssid else new_id
    changed = False
    previous = None
    try:
        if CURRENT_PASSWORD_FILE.exists():
            previous = CURRENT_PASSWORD_FILE.read_bytes()
            _atomic_write_text(CURRENT_PASSWORD_FILE, (
                f"STALE - no current password for {new_label}.\n"
                f"On {timestamp} setup changed the managed WLAN from {old_label} "
                f"to {new_label}.\n"
                f"The previous password must not be given to guests. Run "
                f"rotate_guest_password.py to set a new one.\n"))
            changed = True
        if save is not None:
            save()
    except BaseException as e:
        if previous is not None:
            _restore_published_password(previous, e)
        if isinstance(e, OSError) and not isinstance(e, EnvWriteError):
            raise EnvWriteError(
                f"setup did not save the new WLAN ({e}); .env and "
                f"{CURRENT_PASSWORD_FILE.name} were left unchanged.") from e
        raise
    if HISTORY_LOG.exists():
        try:
            _chmod_secret(HISTORY_LOG)
            with os.fdopen(os.open(HISTORY_LOG, os.O_CREAT | os.O_WRONLY | os.O_APPEND,
                                   0o600), "a", encoding="utf-8") as f:
                _chmod_secret(HISTORY_LOG)
                f.write(f"{timestamp}\t{new_ssid or new_id}\t"
                        f"# TARGET WLAN CHANGED from {old_label} to {new_label}; "
                        f"passwords above are for the previous WLAN\n")
            _chmod_secret(HISTORY_LOG)
        except OSError as e:
            if save is None:
                raise
            raise EnvWriteError(
                f"the new WLAN was saved and {CURRENT_PASSWORD_FILE.name} was "
                f"marked STALE, but the TARGET WLAN CHANGED marker could not be "
                f"added to {HISTORY_LOG} ({e}).") from e
        changed = True
    return changed


def upsert_env(updates: dict) -> None:
    """Insert or update KEY=VALUE pairs in .env, preserving the rest."""
    lines, seen = [], set()
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                key = stripped.split("=", 1)[0].strip()
                if key in updates:
                    lines.append(f"{key}={updates[key]}")
                    seen.add(key)
                    continue
            lines.append(line)
    if not lines:
        lines.append("# Juniper Mist API Configuration")
    for key, val in updates.items():
        if key not in seen:
            lines.append(f"{key}={val}")
    _atomic_write_text(ENV_PATH, "\n".join(lines) + "\n")


def acquire_rotation_lock():
    """Take the same exclusive, non-blocking rotate.lock as a rotation, or exit 1.

    Keep the returned file open while writing the STALE notice and .env.
    """
    f = open(LOCK_FILE, "a+", encoding="utf-8")
    try:
        if os.name == "nt":
            import msvcrt
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        try:
            f.seek(0)
            holder = f.read().strip() or "unknown holder"
        except OSError:
            holder = "unknown holder"
        f.close()
        print(f"ERROR: A rotation is running ({holder}; lock file {LOCK_FILE}). "
              f"Setup did not save the new WLAN; run setup again when it "
              f"finishes.", file=sys.stderr)
        sys.exit(1)
    f.seek(0)
    f.truncate()
    f.write(f"pid {os.getpid()} started "
            f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    f.flush()
    return f


# --------------------------------------------------------------------------- #
# Interactive prompts
# --------------------------------------------------------------------------- #

def prompt_nonempty(label: str) -> str:
    while True:
        value = input(label).strip()
        if value:
            return value
        print("  This value is required.")


def prompt_choice(label: str, valid: set) -> str:
    while True:
        value = input(label).strip()
        if value in valid:
            return value
        print(f"  Please enter one of: {', '.join(sorted(valid, key=_as_int))}")


def _as_int(s):
    try:
        return int(s)
    except ValueError:
        return s


def choose_cloud() -> str:
    print("\nSelect your Mist cloud:")
    for key, (name, url) in CLOUD_ENDPOINTS.items():
        print(f"  {key:>2}. {name:10} - {url}")
    choice = prompt_choice("Enter cloud number (1-12): ", set(CLOUD_ENDPOINTS))
    return CLOUD_ENDPOINTS[choice][1]


# --------------------------------------------------------------------------- #
# Setup steps
# --------------------------------------------------------------------------- #

def collect_and_store_credentials() -> dict:
    """Prompt for creds and validate them. Nothing is written to .env here;
    main() saves them together with the WLAN id under rotate.lock."""
    print("=" * 68)
    print("  GUEST WLAN SETUP - Step 1: API Credentials")
    print("=" * 68)

    while True:
        org_id = prompt_nonempty("\nMist Organization ID: ")
        token = prompt_nonempty("Mist API Token: ")
        api_url = choose_cloud()

        print("\nValidating credentials against Mist...")
        ok, result = validate_credentials(api_url, token, org_id)
        if ok:
            print(f"  Connected to organization: {result}")
            return {"api_url": api_url, "token": token,
                    "org_id": org_id, "org_name": result}
        print(f"  Validation failed: {result}")
        again = input("  Try again? [Y/n]: ").strip().lower()
        if again in ("n", "no"):
            sys.exit(1)


def choose_template(cfg: dict) -> dict:
    """List WLAN templates and let the user pick one."""
    print("\n" + "=" * 68)
    print("  Step 2: Choose a Wireless LAN Template")
    print("=" * 68)

    templates = mist_get_all(cfg, f"/orgs/{cfg['org_id']}/templates", "templates")
    if not templates:
        print("No Wireless LAN Templates found in this org.", file=sys.stderr)
        sys.exit(3)

    templates = sorted(templates, key=lambda t: (t.get("name") or "").lower())
    print()
    for i, tmpl in enumerate(templates, 1):
        print(f"  {i:>2}. {tmpl.get('name', '(unnamed)')}")

    idx = _pick_index("\nSelect a template number: ", len(templates))
    chosen = templates[idx]
    print(f"  Selected template: {chosen.get('name')}")
    return chosen


def choose_guest_wlan(cfg: dict, template: dict) -> dict:
    """List SSIDs in the template and let the user pick a validated guest one."""
    print("\n" + "=" * 68)
    print("  Step 3: Choose the Guest Captive-Portal SSID")
    print("=" * 68)

    wlans = mist_get_all(cfg, f"/orgs/{cfg['org_id']}/wlans", "WLANs")

    template_id = template.get("id")
    scoped = [w for w in wlans if w.get("template_id") == template_id]
    if not scoped:
        print("No SSIDs are assigned to that template.", file=sys.stderr)
        sys.exit(3)

    scoped = sorted(scoped, key=lambda w: (w.get("ssid") or "").lower())
    print()
    for i, w in enumerate(scoped, 1):
        portal = w.get("portal") or {}
        auth = portal.get("auth", "none")
        enabled = "enabled" if w.get("enabled", True) else "disabled"
        guest_tag = ("  <-- guest password portal"
                     if auth == "password" and portal.get("passphrase_enabled") is True
                     else "")
        print(f"  {i:>2}. {w.get('ssid', '(no ssid)'):24} "
              f"[portal.auth={auth}, {enabled}]{guest_tag}")

    while True:
        idx = _pick_index("\nSelect the SSID number: ", len(scoped))
        chosen = scoped[idx]
        # Authoritative re-validation from the single-WLAN endpoint.
        detail = _get_wlan_detail(cfg, chosen)
        if detail is None:
            continue
        portal = detail.get("portal") or {}
        auth = portal.get("auth")
        if auth == "password" and portal.get("passphrase_enabled") is True:
            print(f"  Validated: '{chosen.get('ssid')}' is a guest password portal.")
            return chosen
        if auth == "password":
            print(f"  '{chosen.get('ssid')}' is NOT usable: portal.passphrase_enabled "
                  f"is {portal.get('passphrase_enabled')!r}, so guests are not asked "
                  f"for the portal password. Pick another.")
            continue
        print(f"  '{chosen.get('ssid')}' is NOT a guest portal SSID "
              f"(portal.auth is {auth!r}, expected 'password'). Pick another.")


def _get_wlan_detail(cfg: dict, chosen: dict):
    """GET one WLAN. Returns the WLAN dict, or None if the operator wants to
    pick again. Exits 3 on API errors that retrying cannot fix."""
    ssid = chosen.get("ssid")
    while True:
        status, detail = mist_request(
            "GET", cfg["api_url"], cfg["token"],
            f"/orgs/{cfg['org_id']}/wlans/{chosen['id']}")
        if status == 200 and isinstance(detail, dict):
            return detail
        if status == 200:
            reason = "unexpected response body"
        else:
            reason = f"HTTP {status}"
        print(f"  Could not validate '{ssid}': Mist API error ({reason}): "
              f"{_short(detail)}", file=sys.stderr)
        if status in (401, 403):
            print("ERROR: the API token was rejected while reading the WLAN. "
                  "This is not a problem with the SSID; check the token "
                  "and re-run setup.", file=sys.stderr)
            sys.exit(3)
        if status == 404:
            print("  The WLAN was not found (it may have been deleted). "
                  "Pick another.")
            return None
        if not prompt_yes_no("  Retry validating this SSID?", default=True):
            print("ERROR: could not validate the chosen SSID; setup not "
                  "completed.", file=sys.stderr)
            sys.exit(3)


def _short(body) -> str:
    """Compact representation of an API error body."""
    if isinstance(body, (dict, list)):
        return json.dumps(body)[:300]
    return str(body)[:300]


def _pick_index(prompt: str, count: int) -> int:
    """Prompt for a 1-based selection, return 0-based index."""
    while True:
        raw = input(prompt).strip()
        if raw.isdigit() and 1 <= int(raw) <= count:
            return int(raw) - 1
        print(f"  Enter a number between 1 and {count}.")


def prompt_yes_no(question: str, default: bool = False) -> bool:
    """Ask a yes/no question; return True/False. `default` is used on empty input."""
    suffix = " [Y/n]: " if default else " [y/N]: "
    while True:
        raw = input(question + suffix).strip().lower()
        if not raw:
            return default
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        print("  Please answer y or n.")


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main() -> None:
    cfg = collect_and_store_credentials()
    template = choose_template(cfg)
    wlan = choose_guest_wlan(cfg, template)

    print("\n" + "=" * 68)
    print("  Step 4: Options")
    print("=" * 68)
    backup_pref = prompt_yes_no(
        "\n  Save a JSON backup of the WLAN before each password change?",
        default=False)

    lock = acquire_rotation_lock()
    try:
        previous = read_env()
        invalidated = invalidate_published_password(
            previous.get("MIST_WLAN_ID", ""), previous.get("MIST_WLAN_SSID", ""),
            wlan.get("id", ""), wlan.get("ssid", ""),
            save=lambda: upsert_env({
                "MIST_API_URL": cfg["api_url"],
                "MIST_API_TOKEN": cfg["token"],
                "MIST_ORG_ID": cfg["org_id"],
                "MIST_WLAN_TEMPLATE_ID": template.get("id", ""),
                "MIST_WLAN_ID": wlan.get("id", ""),
                "MIST_WLAN_SSID": wlan.get("ssid", ""),
                "MIST_BACKUP_JSON": "true" if backup_pref else "false",
            }))
    finally:
        lock.close()

    print("\n" + "=" * 68)
    print("  SETUP COMPLETE")
    print("=" * 68)
    print(f"  Organization: {cfg['org_name']}")
    print(f"  Template:     {template.get('name')}")
    print(f"  Guest SSID:   {wlan.get('ssid')}")
    print(f"  WLAN ID:      {wlan.get('id')}")
    print(f"  JSON backups: {'on' if backup_pref else 'off'}")
    print(f"  Saved to:     {ENV_PATH}")
    if invalidated:
        print(f"\n  NOTE: the managed WLAN changed. {CURRENT_PASSWORD_FILE.name} "
              f"was marked STALE;")
        print("  do not hand out the previous password. Run the rotation now to")
        print("  publish a password for the new SSID.")
    print("\n  Next: run  python rotate_guest_password.py  to rotate the password,")
    print("  or schedule it to run unattended (see README.md).")


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(3)
    except EnvWriteError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nCancelled.")
        sys.exit(1)
