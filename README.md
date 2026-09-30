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

Operator steps are in [docs/usage.md](docs/usage.md). Token handling, plaintext
password files, the lock, and the portal update are in [SECURITY.md](SECURITY.md).

---

## Disclaimer

This tool is provided **as is**, without warranty of any kind. It is a
community project and is **not** an official Hewlett Packard Enterprise
(HPE) product. The Mist platform is part of HPE Juniper Networking
(formerly Juniper Networks, acquired by HPE in 2025) — this tool is not
endorsed or supported by HPE, HPE Juniper Networking, or their technical
support organizations (TAC). Use at your own risk.

Unlike a read-only reporting tool, this project **modifies configuration**:
rotating the password issues a `PUT` to the selected guest WLAN in its
Wireless LAN Template. The body is only that WLAN's `portal` object (the
portal settings just read from Mist, with the new password). Other top-level
WLAN fields are omitted from the PUT. The API token therefore needs write
access; scope it as narrowly as your organization allows, test with
`--dry-run` first, consider enabling the pre-change JSON backups, and run
rotations under your normal change-control process.

## Requirements

- Python 3.8+ (nothing else to install).
- A Mist API token with access to the org, and the org's cloud region.

## 1. One-time setup

```
python setup_guest_wlan.py
```

You'll be asked for:

1. **Org ID**, **API Token**, and **Cloud** (a 1–12 menu). These are validated
   against Mist (`GET /api/v1/orgs/{org_id}`). On success the script prints
   the organization name. It does not write `.env` here — not
   `MIST_API_URL`, `MIST_API_TOKEN`, or `MIST_ORG_ID`. Those keys are saved
   later, in one write with the WLAN id, while setup holds `rotate.lock`
   (see [Writing `.env`](#writing-env)).
2. A **Wireless LAN Template** (pick from the list found in your org).
3. The **guest SSID** inside that template. The script confirms with the API
   that the SSID really is a guest captive portal (`portal.auth == "password"`).
   If it isn't, it tells you and lets you pick again.
4. Whether to keep a **JSON backup** of the WLAN before each change (default: no).

### Paging templates and WLANs

Setup loads **every page** of templates and of org WLANs (`mist_get_all`,
`limit=1000`). Requests are:

- `GET /api/v1/orgs/{org_id}/templates?limit=1000&page={n}`
- `GET /api/v1/orgs/{org_id}/wlans?limit=1000&page={n}`

Paging starts at page 1. It stops when a page returns fewer than 1000 items,
or when the `X-Page-Total` header is an integer and `page * 1000` has reached
that total. SSIDs are then filtered to the template you picked
(`template_id`). A page that is not HTTP 200, or whose body is not a list,
prints one line and exits **3**:

```
ERROR: could not list templates (HTTP 401, page 1).
ERROR: could not list WLANs (HTTP 500, page 2).
```

An empty template list, or a template with no SSIDs, also exits **3**.

### Checking the chosen SSID

After you pick a number, setup GETs that WLAN
(`GET /api/v1/orgs/{org_id}/wlans/{wlan_id}`) and uses that response, not the
list row.

- HTTP 200 and `portal.auth == "password"`: accepted.
- HTTP 200 and `portal.auth` is something else: it prints `NOT a guest portal`
  with the actual `portal.auth` value and lets you pick again.
- HTTP 200 whose body is not a WLAN object (`unexpected response body`): it
  prints the error and asks `Retry validating this SSID?` (default yes).
  Answering **no** exits **3**.
- **401** or **403**: stderr includes `HTTP 401` or `HTTP 403` and a short
  excerpt of the body (up to 300 characters), then:

  ```
  ERROR: the API token was rejected while reading the WLAN. This is not a problem with the SSID; check the token and re-run setup.
  ```

  Exit **3**.
- **404**: stderr includes `HTTP 404`. The script says the WLAN was not found
  and returns you to the SSID list.
- **429**, **5xx**, and any other HTTP error: stderr includes `HTTP {status}`
  and a short body excerpt, then the same retry prompt. Answering **no**
  exits **3** with `ERROR: could not validate the chosen SSID; setup not completed.`

A timeout, a connection error, or a non-JSON success body on that GET is the
later-step path below: one `ERROR:` line and exit **3**, with no retry prompt.

### Writing `.env`

Setup writes `.env` **once**, after you choose the template, the guest SSID,
and the backup option. That write runs while setup holds `rotate.lock`. It
stores this run's credentials and the WLAN choice together:

- `MIST_API_URL`, `MIST_API_TOKEN`, `MIST_ORG_ID`
- `MIST_WLAN_TEMPLATE_ID`, `MIST_WLAN_ID`, `MIST_WLAN_SSID`
- `MIST_BACKUP_JSON`

The token, org id, and WLAN id are not written on the step-1 org check
alone. If setup exits before this write, the new token is not stored and any
`.env` already on disk is left as it was. That includes declining another
credential attempt (exit **1**), a template or WLAN list failure (exit
**3**), a WLAN validation failure that exits **3**, Ctrl-C, and a rotation
that already holds `rotate.lock` (exit **1**). On that lock exit the STALE
notice is not written either. The same WLAN id on a later setup still
updates `.env` with this run's token; it does not mark the password files
stale.

`.env` is updated in place as key/value pairs. The existing file is **never
deleted** before the replacement is written. Setup writes
`envwrite.<pid>.tmp` in this folder, flushes and `fsync`s it, then
`os.replace`s it onto `.env`. On Windows, if replace hits `PermissionError`
(hidden `.env` on an SMB share), it clears the hidden attribute and tries
replace again, then overwrites the existing file in place (`r+`, truncate,
`fsync`). The temp file is removed only after the new contents are in place.
If the write still fails, setup exits **1** and the `ERROR:` line names
`envwrite.<pid>.tmp`, which still holds the new settings (including the API
token). The same writer is used when a WLAN switch replaces
`current_password.txt` with a STALE notice.

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

### Switching the managed WLAN

Re-running setup and choosing a **different** `MIST_WLAN_ID` marks the
published password stale **before** `.env` is updated. That update is the
single locked write: this run's API token, org id, and API URL, plus the
new WLAN id.
Choosing the same WLAN leaves `current_password.txt` and
`password_history.log` unchanged. The first setup (no previous WLAN id)
does not create those files.

When `current_password.txt` already exists, it is replaced with a notice
whose first line starts with `STALE`. The previous password is removed from
that file. When `password_history.log` already exists, a marker line is
appended; older lines stay in the log. Setup then prints a NOTE telling you
to run the rotation before handing out a password. See
[docs/usage.md](docs/usage.md#after-setup-changes-the-wlan).

## 2. Rotate the password

Test first without changing anything:

```
python rotate_guest_password.py --dry-run
```

`--dry-run` still reads `.env`, GETs the WLAN, and checks `portal.auth`. It
prints the word it would set and exits **0**. It does not PUT, does not take
`rotate.lock`, and does not write `current_password.txt` or
`password_history.log`.

Then rotate for real:

```
python rotate_guest_password.py
```

A real run takes `rotate.lock` first (see below). On success it:

1. GETs the WLAN and checks it is still a guest `password` portal (exit **2**
   if not; Mist is unchanged).
2. Picks one random school-safe word, and picks again if that word is the
   portal password just read.
3. Optionally saves a JSON backup of that GET under `backups/` (only if you
   enabled backups at setup; override per run with `--backup` /
   `--no-backup`). The backup is written **before** the PUT.
4. PUTs **only** `{"portal": ...}` to
   `PUT /api/v1/orgs/{org_id}/wlans/{wlan_id}`. The `portal` object is the one
   from the GET, with `password` set to the new word. Other top-level WLAN
   fields are not sent.
5. As soon as that PUT returns HTTP 200 with a JSON object, prints and flushes
   the SSID and new password to stdout, **before** the confirming GET and
   **before** any local password file is written:

   ```
   [2026-09-28 06:00:00] Guest WiFi password for SSID 'Guest-WiFi' updated.
       New password: rainbow
   ```

6. GETs the WLAN again and compares `portal.password` to the word it sent. It
   does not treat the PUT response body as confirmation.
7. Writes `current_password.txt` (atomically), then appends
   `password_history.log`.

`current_password.txt` is replaced by writing `current_password.txt.<pid>.tmp`
in this folder, flushing, `fsync`ing, and `os.replace`. The password is the
first line; the lines under it name the SSID, WLAN id, and local time:

```
rainbow
# SSID: Guest-WiFi
# WLAN ID: 00000000-0000-0000-0000-000000000000
# Set: 2026-09-28 06:00:00
```

`password_history.log` gains one tab-separated line:
`timestamp`, SSID, password.

Because the guest password is meant to be shared with visitors, it is stored in
plaintext in those files on purpose. The **API token is never** logged.

If the confirming GET fails, or `portal.password` does not match, the process
exits **3** after the password is already on stdout. Local password files are
left as they were. The mismatch line includes the submitted password:

```
ERROR: Mist accepted the update (submitted password 'rainbow') but the password did not match on read-back. Please verify in the Mist dashboard.
```

If Mist accepted the PUT and the read-back matched, but writing
`current_password.txt` or appending `password_history.log` fails, the process
exits **1**. Stdout already shows the password. The stderr line repeats it:

```
ERROR: Mist now uses password 'rainbow' for SSID 'Guest-WiFi', but saving it locally failed: ...
```

`current_password.txt` is written first. If that replace succeeded, its first
line is the new password even when the history append is what failed. On a
failed replace, the temp file is removed and any previous
`current_password.txt` is left in place.

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

That log receives stdout and stderr, so it will contain guest passwords.

Staff can read the current password any time from `current_password.txt`.
The password is on the first line; the lines below it name the SSID and WLAN ID
it belongs to. If you re-run setup and pick a different WLAN, setup replaces
the file with a **STALE** notice (and adds a marker to `password_history.log`)
until the next rotation publishes a password for the new SSID.

### `rotate.lock`

A real rotation holds an exclusive, non-blocking lock on `rotate.lock` next
to the script, from before the GET until the process exits. POSIX uses
`fcntl.flock` (`LOCK_EX | LOCK_NB`). Windows uses `msvcrt.locking` with
`LK_NBLCK` on one byte. After the lock is acquired the file contains one
line, `pid <pid> started <YYYY-MM-DD HH:MM:SS>`. The operating system
releases the lock when the process exits, including after a crash. A leftover
`rotate.lock` file does not by itself block the next run.

If another rotation holds the lock, this run exits **1** and does not call
Mist:

```
ERROR: Another rotation is already running (pid 1234 started 2026-09-28 06:00:00; lock file /path/to/rotate.lock). Not starting a second one.
```

If the holder text cannot be read, the message says `unknown holder`.
`--dry-run` does not take the lock. Setup holds the same lock while it
writes the STALE notice (only when the WLAN id changes) and while it writes
`.env` once, with the API token, org id, and WLAN id together. If a rotation
holds the lock, setup exits **1** without that write
(`A rotation is running ... Setup did not save the new WLAN`). If
`MIST_WLAN_ID` changed before a rotation got the lock, the rotation exits
**1** without calling Mist.

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
| 1 | Local or configuration error (see below) |
| 2 | The WLAN is not a guest `password` portal (rotation aborts; Mist is unchanged) |
| 3 | Mist API / network error (see below) |

**Exit 1** from `rotate_guest_password.py` covers a missing or invalid `.env`,
a `MIST_API_URL` host outside the twelve Mist clouds, another run holding
`rotate.lock`, a local password-file failure after Mist has accepted the new
password, and Ctrl-C (`Interrupted.`).

**Exit 1** from `setup_guest_wlan.py` covers declining another credential
attempt (`Try again?` answered no), a rotation holding `rotate.lock`
(`A rotation is running ...`; the STALE notice, credentials, and WLAN id
are not written), a failed `.env` or STALE-file write (`EnvWriteError`, the
message names `envwrite.<pid>.tmp`), and Ctrl-C (`Cancelled.`).

**Exit 2** is only the rotation script, when `portal.auth` is not `password`.

**Exit 3** is a Mist or network failure. Both scripts use a 30 second timeout
(`API_TIMEOUT`). `TimeoutError` and `socket.timeout` become a `RuntimeError`
and exit **3**, one stderr line, no Python traceback:

```
ERROR: Timed out after 30s waiting for the Mist API to respond.
```

`URLError`, `OSError`, and `http.client.HTTPException` raised during the call
use the same exit **3** path, with
`ERROR: Connection error reaching Mist API: ...`.

A Mist **success** response (for example HTTP 200) whose body is not empty and
is not JSON is exit **3**, including during `--dry-run`. That includes an HTML
page from Mist or a proxy, and a body that is not valid UTF-8. Schedulers
should treat it as a Mist API error. `rotate_guest_password.py` prints one
line to stderr and does not print a Python traceback. The response body is
left out of the message:

```
ERROR: Mist API returned a non-JSON response (HTTP 200) for GET /orgs/<org-id>/wlans/<wlan-id>.
```

The method, status, and path are the Mist call that failed (a password update
uses `PUT` on that same WLAN path).

`setup_guest_wlan.py` uses the same sentence. While it is checking credentials
the line is `Validation failed: ...` and you can try again; answering **no**
exits **1**. On a later step (listing templates or SSIDs, or re-checking the
chosen SSID) it prints `ERROR: ...` to stderr and exits **3**.

An HTTP **error** response whose body is not JSON is unchanged: the scripts
still use that HTTP status. When `rotate_guest_password.py` cannot complete
the call, it exits **3**.

## Files

| File | Purpose |
|------|---------|
| `setup_guest_wlan.py` | One-time interactive setup |
| `rotate_guest_password.py` | Unattended password rotation |
| `docs/usage.md` | Operator steps |
| `SECURITY.md` | Token, password files, lock, `.env` writes, portal PUT |
| `.env` | API token, org id, and selected WLAN, written together under `rotate.lock` (created by setup; never deleted before a replacement is written) |
| `.env.example` | Reference for the env format |
| `current_password.txt` | Latest guest password on line 1, then SSID / WLAN ID / time (created on first rotate; replaced with a STALE notice if setup switches WLANs) |
| `password_history.log` | Timestamped history (created on first rotate; a `TARGET WLAN CHANGED` marker is appended when setup switches WLANs) |
| `backups/` | Pre-change WLAN JSON snapshots (only if backups enabled) |
| `rotate.lock` | Exclusive lock held for a real rotation and for setup's one `.env` write (`fcntl` / `msvcrt`). A second rotation, or setup while a rotation holds it, exits 1. Not taken on `--dry-run` |

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

## License

[MIT](LICENSE)
