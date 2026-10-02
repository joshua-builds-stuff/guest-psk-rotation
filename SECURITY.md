# Security

What this tool stores, what it sends, and what it does not do. Behavior below
matches `setup_guest_wlan.py` and `rotate_guest_password.py`. Install is
unchanged (Python 3.8+, standard library only).

## API token

The Mist API token, the org id, and the WLAN id are credentials in `.env`.
Examples in this repository use placeholders only.

`setup_guest_wlan.py` writes the token and org id in one update with the
WLAN id, while it holds `rotate.lock`. Step 1 only checks the token with
`GET /api/v1/orgs/{org_id}`. On success it prints the organization name and
keeps the API URL, token, and org id in memory. It does not write `.env`
on that check, and it does not print `Saved credentials to .env`. The write
that records `MIST_WLAN_ID` (and `MIST_WLAN_TEMPLATE_ID`, `MIST_WLAN_SSID`,
and `MIST_BACKUP_JSON`) is the write that records `MIST_API_URL`,
`MIST_API_TOKEN`, and `MIST_ORG_ID`. A partial setup cannot leave a new API
URL, token, or org id next to the previous `MIST_WLAN_ID`. The same WLAN id
on a later setup still updates the token in that write; it does not mark
the password files stale.

If setup never reaches that write, the new token is not stored. Declining
`Try again?` exits **1**. A template or WLAN list failure, or a WLAN
validation failure that gives up, exits **3**. Ctrl-C exits **1**. If a
rotation already holds `rotate.lock`, setup exits **1** and does not write
the STALE notice or `.env`. An existing `.env` stays as it was, including
any previous token.

Both scripts send the token on each Mist call as the header
`Authorization: Token <token>` with `Content-Type: application/json`. The
token is not a query parameter.

The scripts do not write the token to stdout, `current_password.txt`,
`password_history.log`, `rotate.lock`, or the JSON files under `backups/`.
Those backups are the WLAN object from GET, which includes the guest portal
password and does not include the API token. Rotation error text is built
from the HTTP status and a truncated response body (`_short` keeps at most
300 characters of a JSON body). The scripts do not insert the token into
that text.

`.env` is listed in `.gitignore`. `.env.example` has a placeholder token
only. The token still needs permission to read the org, list templates and
WLANs, GET the chosen WLAN, and PUT that WLAN's portal. Scope it as narrowly
as your org allows. This repository does not name a Mist role.

A failed `.env` write leaves `envwrite.<pid>.tmp` in the script folder. That
temp file contains the same keys as `.env`, including `MIST_API_TOKEN`. Treat
it as a secret: move it into place or delete it, and do not commit it.
`.gitignore` does not list `envwrite.*.tmp` by name; it does ignore `.env`.

On Unix those files are mode `0o600`. See [Local file modes](#local-file-modes).

## Local file modes

Secret files and their replacement temp files are opened with mode `0o600`
and then `chmod`ed to `0o600`. On Unix the result is owner read and write
only. Group and other users cannot read them, including when the process
umask would otherwise leave a new file group- or world-readable. When one
of the writes below rewrites or appends a file that already exists, that
file is tightened to `0o600` as well. A file this run does not touch keeps
its previous mode.

The writes that set mode `0o600`:

- `.env`, on setup's one locked write of the API token, org id, and WLAN id.
- `envwrite.<pid>.tmp`, the temp file that writer uses before it replaces
  `.env` or a STALE `current_password.txt`.
- `current_password.txt`, when a rotation replaces it, and when setup writes
  the STALE notice (only if that file already exists and the WLAN id changes).
- `current_password.txt.<pid>.tmp`, rotation's temp file for that replace.
- `password_history.log`, when a rotation creates or appends it, and when
  setup appends the `TARGET WLAN CHANGED` marker (only if the log already
  exists).
- `backups/*.json`, each new pre-change backup, when backups are enabled.

The `backups/` directory uses the process's normal directory mode
(`mkdir`). Each new JSON file inside it is `0o600`. JSON already in `backups/` is left as it
is, so an older backup keeps the mode it was created with. Remove or
replace those older files if other accounts on the host should not read
them.

After an upgrade, the next successful setup tightens `.env`. The next
successful rotation tightens `current_password.txt` and
`password_history.log`. A later setup that keeps the same WLAN id does not
rewrite those two password files, so their modes stay as they were until a
rotation or a WLAN change writes them. A `--dry-run` leaves their modes
unchanged.

`rotate.lock` is still created with the process's normal file mode. The
line stored there is a pid and a start time.

On Windows, `os.chmod` is best-effort: an `OSError` from `chmod` is ignored.
Set filesystem ACLs so only the account that runs setup and rotation can
read `.env`, `envwrite.*.tmp`, `current_password.txt`,
`password_history.log`, and backup JSON.

A scheduler log such as `rotate.log` in the cron example is a file the
shell creates. These scripts set the mode only of the files they write.
Restrict `rotate.log` yourself; it receives guest passwords on stdout.

On Unix, a failed `chmod` fails that write. If it fails while setup is
finishing `.env` or the STALE file, setup exits **1**. If it fails while
rotation is saving `current_password.txt` or appending
`password_history.log` after Mist has accepted the password, rotation exits
**1** and stderr repeats that password (`saving it locally failed`).

## Plaintext guest passwords

The captive-portal password is meant to be shared with visitors. The tools
store it in plaintext on purpose:

- stdout, on the line `New password: <word>`, flushed as soon as the password
  PUT returns HTTP 200 with a JSON object
- `current_password.txt`, word on line 1, then `# Kind:` (`Guest WiFi password`
  when `auth.type` is `open`, otherwise `captive-portal passphrase`),
  `# SSID:`, `# WLAN ID:`, and `# Set:` lines
- `password_history.log`, `timestamp<TAB>SSID<TAB>password`
- `backups/*.json`, inside the WLAN `portal.password` field, when backups
  are enabled (off unless `MIST_BACKUP_JSON` is true or you pass `--backup`)

`.gitignore` ignores `current_password.txt`, `password_history.log`, and
`backups/`. Those files are mode `0o600` on Unix when the scripts write
them. See [Local file modes](#local-file-modes). A scheduler that appends
stdout to a log (the cron example in the README redirects to `rotate.log`)
copies the password into that log. The scripts do not set that log's mode.

When setup switches to a different WLAN, it rewrites `current_password.txt`
(if the file exists) so the old password is no longer in that file. The
history log is append-only: older lines still contain previous passwords,
and a `# TARGET WLAN CHANGED` line marks the switch. Do not treat history
lines above that marker as the password for the new SSID.

## Lock file

`rotate.lock` serializes real runs of `rotate_guest_password.py` so two
rotations cannot publish different words and leave `current_password.txt`
on a word Mist has already replaced. The lock is exclusive and non-blocking:
`fcntl.flock(LOCK_EX | LOCK_NB)` when `os.name` is not `nt`, and
`msvcrt.locking(..., LK_NBLCK, 1)` on Windows. The second process exits **1**
without sending a PUT.

The file contents after a lock is taken are one line:
`pid <pid> started <YYYY-MM-DD HH:MM:SS>`. That line is not the API token,
the org id, or the WLAN id. `.gitignore` ignores `rotate.lock`.

The lock is held by keeping the file open until the rotation process exits.
It is not acquired for `--dry-run`. `setup_guest_wlan.py` holds the same
lock while it writes the STALE notice (only when the WLAN id changes) and
saves credentials together with the WLAN id to `.env` in one write: API
token, org id, API URL, template id, WLAN id, SSID, and backup flag. If a
rotation holds the lock, setup exits **1** without that write. A rotation
re-reads `.env` after taking the lock and exits **1** without a PUT, and
without touching `current_password.txt`, if `MIST_WLAN_ID` changed.

## `.env` protection

Updates go through one writer. It never deletes `.env` before the new bytes
are on disk. Sequence:

1. Write `envwrite.<pid>.tmp` (a name that does not start with a dot) with
   mode `0o600`, `chmod` it to `0o600`, flush, and `fsync`.
2. `os.replace` that temp file onto the destination. On success, `chmod`
   the destination to `0o600` and return.
3. On `PermissionError`, clear the Windows hidden attribute
   (`SetFileAttributesW` with `FILE_ATTRIBUTE_NORMAL`) and `os.replace`
   again. On success, `chmod` the destination to `0o600` and return. On
   other platforms the attribute clear is a no-op.
4. If replace still fails and the destination already exists, `chmod` the
   destination to `0o600`, then overwrite it in place: open `r+`, seek to
   the start, write, truncate, flush, `fsync`, and `chmod` to `0o600`
   again.
5. Delete the temp file only after the new contents are in the destination.

There is no delete-and-then-rename fallback. If every step fails, setup
exits **1** with `EnvWriteError`. The destination is still the previous file
when replace never succeeded, and the error names the temp file that holds
the new copy.

The same writer replaces `current_password.txt` with the STALE notice.
Rotation's writer for a successful password is separate: it opens
`current_password.txt.<pid>.tmp` with mode `0o600`, `chmod`s that temp
file, `fsync`s, `os.replace`s it, then `chmod`s `current_password.txt` to
`0o600`. It deletes that temp file if the replace fails. It does not delete
`current_password.txt` first.

## Portal-only PUT

A password change PUTs this JSON and nothing else at the top level:

```json
{"portal": {"...fields from the GET...": "...", "password": "<new word>"}}
```

`portal` is a copy of `portal` on the WLAN GET that started this rotation,
with `password` set to the new word. Omitted top-level WLAN fields are not
sent, so this PUT does not write back a stale copy of SSID name, VLAN, or
other top-level settings from that snapshot. The script's comment on this
path states that Mist's PUT leaves omitted top-level fields untouched.

The nested `portal` object **is** the snapshot from that GET, plus the new
password. A change someone else made to another portal field after that GET
and before this PUT can be overwritten, because those portal fields are
included. Confirmation is a new GET of the WLAN. The PUT response body is
not used as proof that `portal.password` matches.

`--dry-run` performs the GET and prints a candidate word. It does not PUT.
