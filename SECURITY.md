# Security

What this tool stores, what it sends, and what it does not do. Behavior below
matches `setup_guest_wlan.py` and `rotate_guest_password.py`. Install is
unchanged (Python 3.8+, standard library only).

## API token

The Mist API token is written only to `.env` as `MIST_API_TOKEN`, by
`setup_guest_wlan.py`, after `GET /api/v1/orgs/{org_id}` succeeds. Both
scripts send it on each Mist call as the header `Authorization: Token <token>`
with `Content-Type: application/json`. The token is not a query parameter.

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

The writers use `open()` with the default mode. They do not call `chmod` or
set a Windows ACL. On Unix the file mode follows the process umask.

## Plaintext guest passwords

The captive-portal password is meant to be shared with visitors. The tools
store it in plaintext on purpose:

- stdout, on the line `New password: <word>`, flushed as soon as the password
  PUT returns HTTP 200 with a JSON object
- `current_password.txt`, word on line 1, then `# SSID:`, `# WLAN ID:`, and
  `# Set:` lines
- `password_history.log`, `timestamp<TAB>SSID<TAB>password`
- `backups/*.json`, inside the WLAN `portal.password` field, when backups
  are enabled (off unless `MIST_BACKUP_JSON` is true or you pass `--backup`)

`.gitignore` ignores `current_password.txt`, `password_history.log`, and
`backups/`. A scheduler that appends stdout to a log (the cron example in
the README redirects to `rotate.log`) copies the password into that log.

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
`pid <pid> started <YYYY-MM-DD HH:MM:SS>`. `.gitignore` ignores `rotate.lock`.

The lock is held by keeping the file open until the rotation process exits.
It is not acquired for `--dry-run`. `setup_guest_wlan.py` holds the same
lock while it writes the STALE notice and saves the WLAN to `.env`; if a
rotation holds it, setup exits **1** without saving. A rotation re-reads
`.env` after taking the lock and exits **1** without a PUT, and without
touching `current_password.txt`, if `MIST_WLAN_ID` changed.

## `.env` protection

Updates go through one writer. It never deletes `.env` before the new bytes
are on disk. Sequence:

1. Write `envwrite.<pid>.tmp` (a name that does not start with a dot), flush,
   and `fsync`.
2. `os.replace` that temp file onto the destination.
3. On `PermissionError`, clear the Windows hidden attribute
   (`SetFileAttributesW` with `FILE_ATTRIBUTE_NORMAL`) and `os.replace` again.
   On other platforms that step is a no-op.
4. If replace still fails and the destination already exists, overwrite it
   in place: open `r+`, seek to the start, write, truncate, flush, `fsync`.
5. Delete the temp file only after the new contents are in the destination.

There is no delete-and-then-rename fallback. If every step fails, setup
exits **1** with `EnvWriteError`. The destination is still the previous file
when replace never succeeded, and the error names the temp file that holds
the new copy.

The same writer replaces `current_password.txt` with the STALE notice.
Rotation's writer for a successful password is separate: it uses
`current_password.txt.<pid>.tmp`, `fsync`, and `os.replace`, and it deletes
that temp file if the replace fails. It does not delete
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
