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
     them against the Mist API, and writes them to `.env`.
  2. Lists every Wireless LAN Template in the org; you pick one.
  3. Lists the SSIDs in that template (annotated with their portal auth
     type); you pick the guest SSID you want to manage.
  4. Validates via the API that the chosen SSID has a guest captive portal
     (portal.auth == "password"). If it does not, it says so and lets you
     pick again.
  5. Asks whether to keep a JSON backup of the WLAN before each change.
  6. Records the WLAN ID (and your choices) in `.env`.

After this runs once, rotate_guest_password.py can rotate the password
fully unattended (schedule it with Task Scheduler / cron).

Pure Python standard library only. The only network calls are to Mist.
"""

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

SCRIPT_DIR = Path(__file__).resolve().parent
ENV_PATH = SCRIPT_DIR / ".env"
API_TIMEOUT = 30

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

def mist_request(method, api_url, token, path, body=None):
    """Perform a Mist API request. Returns (status_code, parsed_json_or_text)."""
    url = f"{api_url.rstrip('/')}/api/v1{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Token {token}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=API_TIMEOUT) as resp:
            raw = resp.read()
            return resp.getcode(), (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            detail = json.loads(raw)
        except Exception:
            detail = raw.decode("utf-8", errors="replace")[:300]
        return e.code, detail
    except urllib.error.URLError as e:
        raise RuntimeError(f"Connection error reaching Mist API: {e.reason}")


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


def _atomic_write_text(path: Path, content: str) -> None:
    """Write text to `path` atomically and robustly.

    Writes to a temp file (with a normal, non-dot name) then os.replace()s it
    into place. This is crash-safe AND sidesteps a Windows quirk: dotfiles on a
    Samba/SMB share are shown as 'hidden', and opening an existing hidden file
    with mode 'w' raises PermissionError. os.replace can overwrite a hidden
    target; if it can't, clear the attribute or fall back to remove + rename.
    """
    tmp = path.parent / f"envwrite.{os.getpid()}.tmp"
    tmp.write_text(content, encoding="utf-8")
    try:
        try:
            os.replace(tmp, path)
        except PermissionError:
            _clear_hidden(path)
            try:
                os.replace(tmp, path)
            except PermissionError:
                if path.exists():
                    os.remove(path)
                os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


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
    """Prompt for creds, validate, and write them to .env."""
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
            upsert_env({
                "MIST_API_URL": api_url,
                "MIST_API_TOKEN": token,
                "MIST_ORG_ID": org_id,
            })
            print(f"  Saved credentials to {ENV_PATH.name}")
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

    status, templates = mist_request(
        "GET", cfg["api_url"], cfg["token"], f"/orgs/{cfg['org_id']}/templates")
    if status != 200 or not isinstance(templates, list):
        print(f"ERROR: could not list templates (HTTP {status}).", file=sys.stderr)
        sys.exit(3)
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

    status, wlans = mist_request(
        "GET", cfg["api_url"], cfg["token"], f"/orgs/{cfg['org_id']}/wlans")
    if status != 200 or not isinstance(wlans, list):
        print(f"ERROR: could not list WLANs (HTTP {status}).", file=sys.stderr)
        sys.exit(3)

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
        guest_tag = "  <-- guest password portal" if auth == "password" else ""
        print(f"  {i:>2}. {w.get('ssid', '(no ssid)'):24} "
              f"[portal.auth={auth}, {enabled}]{guest_tag}")

    while True:
        idx = _pick_index("\nSelect the SSID number: ", len(scoped))
        chosen = scoped[idx]
        # Authoritative re-validation from the single-WLAN endpoint.
        status, detail = mist_request(
            "GET", cfg["api_url"], cfg["token"],
            f"/orgs/{cfg['org_id']}/wlans/{chosen['id']}")
        portal = (detail or {}).get("portal") or {} if status == 200 else {}
        auth = portal.get("auth")
        if auth == "password":
            print(f"  Validated: '{chosen.get('ssid')}' is a guest password portal.")
            return chosen
        print(f"  '{chosen.get('ssid')}' is NOT a guest portal SSID "
              f"(portal.auth is {auth!r}, expected 'password'). Pick another.")


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

    upsert_env({
        "MIST_WLAN_TEMPLATE_ID": template.get("id", ""),
        "MIST_WLAN_ID": wlan.get("id", ""),
        "MIST_WLAN_SSID": wlan.get("ssid", ""),
        "MIST_BACKUP_JSON": "true" if backup_pref else "false",
    })

    print("\n" + "=" * 68)
    print("  SETUP COMPLETE")
    print("=" * 68)
    print(f"  Organization: {cfg['org_name']}")
    print(f"  Template:     {template.get('name')}")
    print(f"  Guest SSID:   {wlan.get('ssid')}")
    print(f"  WLAN ID:      {wlan.get('id')}")
    print(f"  JSON backups: {'on' if backup_pref else 'off'}")
    print(f"  Saved to:     {ENV_PATH}")
    print("\n  Next: run  python rotate_guest_password.py  to rotate the password,")
    print("  or schedule it to run unattended (see README.md).")


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(3)
    except KeyboardInterrupt:
        print("\nCancelled.")
        sys.exit(1)
