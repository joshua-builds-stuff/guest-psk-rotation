# Using guest password rotation

Operator steps for `setup_guest_wlan.py` and `rotate_guest_password.py`.
Install is unchanged: Python 3.8 or newer, standard library only, no `pip`.
Run the commands from the folder that contains the scripts. Details of what
the scripts send to Mist are in the [README](../README.md). How secrets are
stored is in [SECURITY.md](../SECURITY.md).

## Setup

Run once, and again whenever the managed guest SSID should change:

```
python setup_guest_wlan.py
```

The prompts are:

1. **Mist Organization ID**, **Mist API Token**, and a **cloud number (1–12)**.
   Setup calls `GET /api/v1/orgs/{org_id}` on the host you picked. On success
   it prints `Connected to organization: <name>`. It does not write `.env`
   and it does not print `Saved credentials to .env`. The API URL, token,
   and org id stay in memory until the locked write at the end of setup,
   which stores them with the WLAN id. See [Lock file](#lock-file).
2. A **Wireless LAN Template**, numbered from the full org list.
3. The **guest SSID** in that template. A row is tagged
   ` <-- guest password portal` only when that list row has
   `portal.auth=password` and `passphrase_enabled` exactly true. Setup still
   GETs that WLAN and accepts it only when the GET body is an object whose
   `portal.auth` is `password` and whose `portal.passphrase_enabled` is
   exactly true. It does not turn the passphrase on for you.
4. Whether to save a JSON backup before each password change. Empty input
   means **no** (`MIST_BACKUP_JSON=false`).

Cloud menu:

| # | Name | API host |
|---|------|----------|
| 1 | Global 01 | `https://api.mist.com` |
| 2 | Global 02 | `https://api.gc1.mist.com` |
| 3 | Global 03 | `https://api.ac2.mist.com` |
| 4 | Global 04 | `https://api.gc2.mist.com` |
| 5 | Global 05 | `https://api.gc4.mist.com` |
| 6 | EMEA 01 | `https://api.eu.mist.com` |
| 7 | EMEA 02 | `https://api.gc3.mist.com` |
| 8 | EMEA 03 | `https://api.ac6.mist.com` |
| 9 | EMEA 04 | `https://api.gc6.mist.com` |
| 10 | APAC 01 | `https://api.ac5.mist.com` |
| 11 | APAC 02 | `https://api.gc5.mist.com` |
| 12 | APAC 03 | `https://api.gc7.mist.com` |

Templates and WLANs are paged with `limit=1000` until a short page comes back
or `X-Page-Total` says the list is finished, so a template or SSID past the
first page is still listed. A failed page exits **3** with
`ERROR: could not list templates (HTTP ..., page ...).` or the same sentence
for `WLANs`.

### When credential checks fail

Setup prints `Validation failed: ...` and asks `Try again? [Y/n]`. That
includes a bad token, a bad org id, an unrecognized cloud URL, a timeout
(`Timed out after 30s waiting for the Mist API to respond.`), a connection
error, and a non-JSON success body. Answering **no** exits **1** and leaves
`.env` unchanged. A check that succeeds also leaves `.env` unchanged. The
token, org id, and API URL are stored only in the locked write with the
WLAN id, after the template, SSID, and backup steps finish. If one of those
later steps exits **3**, or a rotation holds `rotate.lock` (setup exits
**1**), the token you typed is not saved. If `.env` already exists, it keeps
its previous API URL, token, org id, and WLAN id. A partial setup cannot
leave a new token or org next to the previous WLAN id.

### When the SSID check fails

| What you see | What to do |
|--------------|------------|
| `NOT a guest portal SSID` and a `portal.auth` value | The GET succeeded. Pick a WLAN whose portal auth is `password`. |
| `NOT usable` and a `portal.passphrase_enabled` value | The GET succeeded and `portal.auth` is `password`, but the passphrase flag is missing or not exactly true. Guests are not asked for `portal.password`. Pick another SSID, or enable the passphrase in Mist and run setup again. The script does not set the flag. |
| `Could not validate '...': Mist API error (HTTP 401)` or `HTTP 403`, then `ERROR: the API token was rejected...` | Exit **3**. The SSID was not rejected. Fix the token and run setup again. |
| `HTTP 404` and `The WLAN was not found` | Pick another SSID from the list. |
| `HTTP 429`, `HTTP 500`, or another HTTP status, then `Retry validating this SSID? [Y/n]` | Default is yes. Answering **no** exits **3** (`could not validate the chosen SSID; setup not completed`). |
| `unexpected response body` and the same retry prompt | The HTTP status was 200 and the body was not a WLAN object. Retry or exit **3**. |
| `ERROR: Timed out after 30s...`, `ERROR: Connection error...`, or `ERROR: Mist API returned a non-JSON response...` | Exit **3** immediately. This path has no retry prompt. Run setup again when Mist is reachable. |

### If `.env` cannot be replaced

Setup never deletes `.env` and then renames a temp file over the gap. It
writes `envwrite.<pid>.tmp`, `fsync`s, and replaces `.env`. If replace and
the in-place overwrite both fail, the process exits **1** and the error names
that temp file. The temp file has the new settings, including the API token,
and it is created mode `0o600`. Move it to `.env` only after you can write
in this folder, and do not leave it behind.

Do not use that recovery when the error says the file already has the new
contents and only the mode change failed. Replace already succeeded, and
there is no `envwrite.<pid>.tmp` to rename. On a WLAN switch, see
[If a WLAN switch exits 1 after replace](#if-a-wlan-switch-exits-1-after-replace).

### Who can read the saved files

On Unix, a finished setup leaves `.env` mode `0o600`: the owner can read and
write it, and group and other users cannot. `envwrite.<pid>.tmp` is created
with that same mode. The mode is set again with `chmod`, so a permissive
umask does not leave the token readable by other accounts on the machine.

On Windows, `os.chmod` is best-effort and an error from `chmod` is ignored.
Set a filesystem ACL so only the account that runs setup and rotation can
read `.env`, `envwrite.*.tmp`, `current_password.txt`,
`password_history.log`, and any `backups/*.json`.

A successful rotation uses the same mode for `current_password.txt`,
`current_password.txt.<pid>.tmp`, `password_history.log`, and each new file
under `backups/` when backups are on. Appending the history log tightens a
log that was created earlier with a looser mode. Setup's STALE rewrite uses
the same `0o600` writer for `current_password.txt`.

The next successful setup tightens `.env`, including when you keep the same
WLAN. The next successful rotation tightens `current_password.txt` and
`password_history.log`. A `--dry-run` leaves those modes unchanged. JSON
files already in `backups/` keep the mode they were created with.

`rotate.log` from the cron line below is created by the shell. Restrict it
yourself. `rotate.lock` keeps the process's normal create mode; its text is
a pid and a start time. The file list is in
[SECURITY.md](../SECURITY.md#local-file-modes).

## Dry run

```
python rotate_guest_password.py --dry-run
```

Optional: `--env path\to\.env` if the file is not `.env` beside the script.
`--backup` and `--no-backup` are accepted and ignored for the PUT, because a
dry run does not write a backup and does not change Mist.

What it does:

- Loads `.env` (exit **1** if it is missing, incomplete, or the API host is
  not one of the twelve clouds).
- Does **not** lock `rotate.lock`.
- GETs the configured WLAN.
- Exits **2** if `portal.auth` is not `password`, or if `portal.auth` is
  `password` but `portal.passphrase_enabled` is missing or not exactly true.
  Nothing is PUT. The passphrase flag is not turned on.
- If those checks pass and `auth.type` is not `open` (missing counts as not
  open), prints a WARNING on stderr that `auth.psk` was not changed. It
  still does not change Mist.
- Prints the word it would set, then `[DRY RUN] No changes were sent to Mist.`
  The line says `would set new Guest WiFi password` only when `auth.type` is
  `open`. Otherwise it says `would set new captive-portal passphrase`.
- Exits **0**.

It does not write `current_password.txt` or `password_history.log`. A timeout
or other Mist error on the GET is still exit **3**.

## Rotate

```
python rotate_guest_password.py
```

Per-run backup switches: `--backup` or `--no-backup`. They override
`MIST_BACKUP_JSON` for that process only.

What you should see on success:

```
[2026-09-28 06:00:00] Guest WiFi password for SSID 'Guest-WiFi' updated.
    New password: rainbow
    Recorded in:  current_password.txt and password_history.log
```

That first line says `Guest WiFi password` only when `auth.type` is `open`.
Otherwise it says `Captive-portal passphrase`. If `auth.type` is not `open`,
stderr also has a WARNING that only `portal.password` was rotated and that
`auth.psk` was not changed. Do not replace the Wi-Fi passphrase in Mist with
the portal word. The run still exits **0** when the rest succeeds.

If backups are on, a third line names the JSON file under `backups/`.

Give guests the word on the `New password:` line, or the **first line** of
`current_password.txt`:

```
rainbow
# Kind: Guest WiFi password
# SSID: Guest-WiFi
# WLAN ID: <MIST_WLAN_ID>
# Set: 2026-09-28 06:00:00
```

When `auth.type` is not `open`, the Kind line is
`# Kind: captive-portal passphrase`. The `#` lines are labels, not part of
the password. `password_history.log` appends
`timestamp<TAB>SSID<TAB>password` and does not include the kind.

The password line is flushed as soon as Mist accepts the PUT, before the
script GETs the WLAN again and before it writes those files. Keep the
scheduler's stdout. If the process ends before `Recorded in:`:

- Exit **3** and `password did not match on read-back` (or another `ERROR:`
  from the confirming GET): Mist accepted a PUT, and stdout has the submitted
  password. `current_password.txt` was not updated for this run. Check the
  Mist dashboard before handing the old file to guests.
- Exit **1** and `Mist now uses password '...' ... saving it locally failed`:
  read-back matched. Use the password in that error (it is the same word as
  stdout). Open `current_password.txt`. If line 1 matches, the history append
  failed. If the file is missing, or it still shows the previous word or a
  `STALE` notice, the replace failed and any previous file was left in place.

The PUT body is `{"portal": ...}` only: the portal object from the GET that
started this run, with `password` replaced. The script then GETs the WLAN
again to confirm `portal.password`.

## Scheduling

The rotation script does not prompt. Point the scheduler at the script with
the working directory set to this folder (the script also finds `.env` next
to itself).

**Windows Task Scheduler**, daily at 06:00:

```
schtasks /Create /TN "Guest WiFi Rotate" /SC DAILY /ST 06:00 ^
  /TR "python \"C:\path\to\guest-psk-rotation\rotate_guest_password.py\""
```

**cron**, daily at 06:00:

```
0 6 * * *  /usr/bin/python3 /path/to/rotate_guest_password.py >> /path/to/rotate.log 2>&1
```

`rotate.log` will contain guest passwords. Restrict that file yourself;
the rotation script sets modes only on the files it writes.

Treat exit codes as in the table below. Overlapping real runs are serialized
by the lock: the second exits **1** and must not be retried in a tight loop
while the first is still running. A later schedule slot is enough.

## Lock file

`rotate.lock` sits next to the scripts. A real rotation creates or opens it
and takes an exclusive non-blocking lock (`fcntl.flock` on Linux and macOS,
`msvcrt.locking` `LK_NBLCK` of 1 byte on Windows). `--dry-run` does not lock.
Setup holds the same `rotate.lock` while it writes the STALE notice (only
when the WLAN id changes) and while it writes `.env` once. That one write
sets `MIST_API_URL`, `MIST_API_TOKEN`, `MIST_ORG_ID`,
`MIST_WLAN_TEMPLATE_ID`, `MIST_WLAN_ID`, `MIST_WLAN_SSID`, and
`MIST_BACKUP_JSON` together. Step 1 does not write the credential keys on
its own. If a rotation holds the lock, setup exits **1** without that
write: the new token is not saved, the STALE notice is not written, and the
previous `.env` stays as it was.

While the lock is held, the file's text is:

```
pid 1234 started 2026-09-28 06:00:00
```

That line is what a second run prints. It is a pid and a start time, not the
guest password, the API token, the org id, or the WLAN id.

If a rotation prints `Another rotation is already running`, or setup prints
`A rotation is running ... Setup did not save the new WLAN`, wait until that
pid exits. Then run the rotation or setup again.
Deleting `rotate.lock` is not required. The lock is the operating-system
lock on the open file; when the holder exits (or is killed) the lock is
released even if the file remains. The next rotation truncates the file and
writes its own pid line.

## Exit codes

| Code | `rotate_guest_password.py` | `setup_guest_wlan.py` |
|------|----------------------------|------------------------|
| 0 | Password rotated, or `--dry-run` finished | Setup finished and printed `SETUP COMPLETE` |
| 1 | Bad or missing `.env`, API host not a Mist cloud, lock busy, local password file failed after Mist accepted the password, or Ctrl-C | Credential prompt cancelled, a rotation holds `rotate.lock` (credentials and the WLAN were not saved), `.env` / STALE write failed, or Ctrl-C. A mode-only failure after replace still exits 1 but keeps the new file contents |
| 2 | `portal.auth` is not `password`, or `portal.passphrase_enabled` is not exactly true. Nothing was PUT | Not used |
| 3 | Mist HTTP error, timeout (30s), connection error, non-JSON success body, or read-back mismatch | Same Mist failures on later steps; list-page failure; 401/403 while reading the chosen WLAN; validation retry declined |

Timeout text, both scripts:

```
ERROR: Timed out after 30s waiting for the Mist API to respond.
```

Non-JSON success text (body omitted), both scripts:

```
ERROR: Mist API returned a non-JSON response (HTTP 200) for GET /orgs/<org-id>/wlans/<wlan-id>.
```

During setup's credential prompt, that same failure is prefixed
`Validation failed:` and can be retried.

A failed read of an HTTP error body (`OSError` or
`http.client.HTTPException`, such as `IncompleteRead` or
`ConnectionResetError`) is the connection-error path above, not the HTTP
status. One `ERROR: Connection error reaching Mist API: ...` line, exit
**3**, no traceback. An HTTP error body that is read, including one that is
not JSON, still uses that HTTP status.

## After setup changes the WLAN

When setup saves a WLAN id that differs from the `MIST_WLAN_ID` already in
`.env`, it updates the local password files **before** it writes `.env`.
That `.env` write also stores this run's API token, org id, and API URL
together with the new WLAN id:

- If `current_password.txt` exists, it is replaced. The new text starts with
  `STALE` and does not contain the previous password:

  ```
  STALE - no current password for 'Guest-Events' (<new-id>).
  On 2026-09-28 12:00:00 setup changed the managed WLAN from 'Guest-WiFi' (<old-id>) to 'Guest-Events' (<new-id>).
  The previous password must not be given to guests. Run rotate_guest_password.py to set a new one.
  ```

- If `password_history.log` exists, one line is appended:
  `timestamp<TAB><new ssid><TAB># TARGET WLAN CHANGED from '<old ssid>' (<old-id>) to '<new ssid>' (<new-id>); passwords above are for the previous WLAN`
  Lines above that marker are the previous WLAN. Do not read them out as the
  current guest password.

- The console NOTE says the file was marked STALE.

Then run:

```
python rotate_guest_password.py
```

Wait until you see `Recorded in:`. The first line of `current_password.txt`
should be a single word again. `# Kind:` says `Guest WiFi password` only
when the new WLAN's `auth.type` is `open`; otherwise it says
`captive-portal passphrase`. The `# SSID:` / `# WLAN ID:` lines should match
the new guest network. Hand that word out. Do not copy it into `auth.psk`.

Choosing the **same** WLAN id on a later setup leaves both password files
as they are. A first-time setup, with no previous `MIST_WLAN_ID`, does not
create them; the first real rotation does.

If only one of the two files exists, only that file is updated. If neither
exists, there is nothing to mark and there is no NOTE.

### If a WLAN switch exits 1 after replace

On Unix, setup can exit **1** after `os.replace` succeeded and only setting
mode `0600` failed. The error says the file already has the new contents and
that only the mode change failed. This is not a rolled-back switch, and
`SETUP COMPLETE` is not printed:

- `current_password.txt` stays the STALE notice. The previous password is
  not written back.
- `.env` has this run's token and the new WLAN id. If the mode failure was
  on the STALE file, that `.env` write still runs. If it was on `.env`, the
  new contents are already there.
- If `password_history.log` already exists, the `TARGET WLAN CHANGED` marker
  is still appended.

Do not hand out a password from the STALE file. Restrict the file named in
the error to its owner, then run the rotation. On Windows, a `chmod` error
is ignored, so this path does not apply.

If the write fails before the destination is replaced, setup restores
`current_password.txt` to the previous password, does not append the marker,
and leaves `.env` on the previous WLAN id. That error names
`envwrite.<pid>.tmp`.
