# Guest WiFi Password Rotation (Juniper Mist)

Two small, self-contained Python tools for a school's guest WiFi. They rotate
the **guest captive-portal password** on a Mist WLAN to a new, easy-to-remember,
school-safe word (for example `apples`, `rainbow`, `penguin`). The password is
drawn from a curated, adversarially screened list of **1200 wholesome words**,
each at least 6 characters long.

- **`setup_guest_wlan.py`** — run **once**, interactively, to select which
  guest SSID to manage and to create `.env`.
- **`rotate_guest_password.py`** — run any time (manually or **scheduled**) to
  set a new random password. Runs fully **unattended** — no prompts.

Both scripts use the **Python standard library only** (no `pip install`), and the
only network traffic is to the Mist API.

---

## Disclaimer

This tool is provided **as is**, without warranty of any kind. It is a
community project and is **not** an official Hewlett Packard Enterprise
(HPE) product. The Mist platform is part of HPE Juniper Networking
(formerly Juniper Networks, acquired by HPE in 2025) — this tool is not
endorsed or supported by HPE, HPE Juniper Networking, or their technical
support organizations (TAC). Use at your own risk.

Unlike a read-only reporting tool, this project **modifies configuration**:
rotating the password issues a `PUT` that updates the selected guest WLAN in
its Wireless LAN Template — that is its entire purpose, and nothing else is
changed. The API token therefore needs write access; scope it as narrowly as
your organization allows, test with `--dry-run` first, consider enabling the
pre-change JSON backups, and run rotations under your normal change-control
process.

## Requirements

- Python 3.8+ (nothing else to install).
- A Mist API token with access to the org, and the org's cloud region.

## 1. One-time setup

```
python setup_guest_wlan.py
```

You'll be asked for:

1. **Org ID**, **API Token**, and **Cloud** (a 1–12 menu). These are validated
   against Mist and written to `.env`.
2. A **Wireless LAN Template** (pick from the list found in your org).
3. The **guest SSID** inside that template. The script confirms with the API
   that the SSID really is a guest captive portal (`portal.auth == "password"`).
   If it isn't, it tells you and lets you pick again.
4. Whether to keep a **JSON backup** of the WLAN before each change (default: no).

The result is saved to `.env`:

```
MIST_API_URL=https://api.mist.com
MIST_API_TOKEN=...            # secret - keep private
MIST_ORG_ID=...
MIST_WLAN_TEMPLATE_ID=...
MIST_WLAN_ID=...
MIST_WLAN_SSID=Guest-WiFi
MIST_BACKUP_JSON=false        # save a WLAN JSON backup before each change?
```

## 2. Rotate the password

Test first without changing anything:

```
python rotate_guest_password.py --dry-run
```

Then rotate for real:

```
python rotate_guest_password.py
```

On success it:

- generates one random school-safe word,
- verifies the WLAN is still a guest `password` portal (aborts if not),
- optionally saves a JSON backup of the WLAN under `backups/` (only if you
  enabled backups at setup; override per run with `--backup` / `--no-backup`),
- PUTs the change to Mist and reads it back to confirm,
- writes the **new password** to:
  - `current_password.txt` (latest password, overwritten each run),
  - `password_history.log` (timestamped audit trail),
  - and prints it to the screen.

Because the guest password is meant to be shared with visitors, it is stored in
plaintext in those files on purpose. The **API token is never** logged.

## 3. Schedule it (unattended)

The rotation script needs no input, so any scheduler works.

**Windows Task Scheduler** (rotate every morning at 6:00):

```
schtasks /Create /TN "Guest WiFi Rotate" /SC DAILY /ST 06:00 ^
  /TR "python \"C:\path\to\guest-psk-rotation\rotate_guest_password.py\""
```

**cron** (Linux/macOS, daily at 06:00):

```
0 6 * * *  /usr/bin/python3 /path/to/rotate_guest_password.py >> /path/to/rotate.log 2>&1
```

Staff can read the current password any time from `current_password.txt`.

## Modifying the password list

The candidate words live in **`rotate_guest_password.py`**, in the block that
starts with `_WORDS = sorted(set("""` (just under the "Word list" comment near
the top of the file). Each word is plain text separated by spaces or newlines
inside the triple-quoted string.

To change the list, edit that block:

- **Add** words by typing them into the string; **remove** words by deleting them.
- Duplicates and ordering don't matter — `sorted(set(...))` de-duplicates and
  sorts the list automatically when the script runs.
- Save the file. The **next rotation uses the new list immediately** — there is
  nothing to rebuild or reinstall.

Keep to these conventions. They match the current list but are **not enforced at
run time**, so an out-of-policy entry would be used as-is:

- one single word per entry, letters `a–z` only, all lowercase,
- at least 6 characters,
- school-appropriate (see the review checklist under *Deployment & review notes*).

Optional sanity check after editing (run from this folder):

```
python -c "import rotate_guest_password as r; w=r._WORDS; print(len(w),'words; shortest',min(map(len,w))); print('violations:',[x for x in w if not(x.isalpha() and x.islower() and len(x)>=6)][:20])"
```

## Exit codes (for schedulers)

| Code | Meaning |
|------|---------|
| 0 | Success (or `--dry-run` completed) |
| 1 | Configuration error (missing/invalid `.env`) |
| 2 | The WLAN is not a guest `password` portal (nothing changed) |
| 3 | Mist API / network error |

## Files

| File | Purpose |
|------|---------|
| `setup_guest_wlan.py` | One-time interactive setup |
| `rotate_guest_password.py` | Unattended password rotation |
| `.env` | Credentials + selected WLAN (created by setup) |
| `.env.example` | Reference for the env format |
| `current_password.txt` | Latest guest password (created on first rotate) |
| `password_history.log` | Timestamped history (created on first rotate) |
| `backups/` | Pre-change WLAN JSON snapshots (only if backups enabled) |

## Deployment & review notes

This project generates and updates the **captive-portal password** used in an
HPE Juniper Mist environment. The rotation draws from a curated list of simple,
lowercase, single-word, easy-to-remember passwords — currently **1,200**
candidate words, each at least 6 characters, chosen to be appropriate for K-12
environments.

### Important implementation note

While the password list was built with K-12 suitability in mind and screened for
appropriateness, **the team deploying this solution is responsible for validating
the final password set before production use.** No password list should be treated
as automatically approved without review by the implementing organization.

Before implementation, review the full list (see *Modifying the password list*
above) to confirm it meets your organization's standards for:

- age-appropriate language,
- school-district policy,
- cultural sensitivity,
- local compliance requirements,
- security and operational requirements.

### Intended use

This tool supports automated or semi-automated captive-portal password rotation
for guest or student-access workflows in HPE Juniper Mist. Before running it in
production, the implementation team should confirm the appropriate Mist
**organization, Wireless LAN Template, WLAN/SSID, and guest captive-portal
configuration**, along with the relevant change-control process.

> **Scope:** this tool operates at the **org level** — it targets a guest WLAN
> that belongs to a Wireless LAN Template (referenced by `MIST_WLAN_ID`). It does
> not select an individual site; a template-derived WLAN applies wherever that
> template is assigned. Only WLANs whose guest portal uses `portal.auth ==
> "password"` are eligible — the scripts verify this and refuse anything else.
