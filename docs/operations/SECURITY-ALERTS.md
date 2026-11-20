# Security alerts

The hub watches its own security log and emails `ADMIN_EMAILS` when something needs a person to look at it now.
This page lists every security alert, what it means and what to do. The alerts about disk space, backups, failing
jobs and the leaver check are in MONITORING.md. Every event in the security log is listed in RUNBOOK.md, "Alerts".

Approval: Signed off (assumed for delivery, 2026-11-20).

## How an alert reaches a person

- **Email** to `ADMIN_EMAILS`, the shared IT mailbox or ticket queue (MONITORING.md). The IT service desk reads it
  every working day. The subject starts "Staff hub:" and the email ends with the name of the section below to read.
- **The security log.** Every alert also writes a `security_alert` line (level WARNING) with the alert's name in
  `alert` and the event that set it off in `trigger`. Supreme's SIEM reads the log (MONITORING.md). Set it to
  **page the IT on-call engineer, day or night,** on `security_alert` lines whose alert is "Admin rights changed" or
  "Many failed sign-ins". The others can wait for the next working morning.
- If the mail relay is down, the email is lost but the log line is still written, so the SIEM still sees it.

The emails hold the account's email address, the network address and the file or change involved. They never hold
posts, chats or passwords.

## The alerts

| Alert | Sent when | Who looks, how fast |
|---|---|---|
| Admin rights changed | Every time someone is given or loses staff status or superuser, joins or leaves a role (group), is given or loses a permission, or a role's permissions change | IT on-call, within the hour |
| Many failed sign-ins | 10 failed or refused sign-ins within 15 minutes, across the whole hub | IT on-call, within the hour |
| One person keeps hitting the limits | One person hits an activity limit 5 times within an hour | IT service desk, same working day |
| One person is downloading many files | One person downloads 100 files within a day | IT service desk, same working day |
| One person keeps exporting their data | One person uses "Download my data" 3 times within a day | IT service desk, same working day |

**How counting works.** A count starts with the first event and runs for its window (15 minutes, an hour or a day).
The email goes out when the count reaches the number. After that, no more email for that alert (and that person)
until the window ends, so an attack can't flood the mailbox. Always read the log for the full picture: the email
only shows the event that reached the number.

The numbers live in `hub/alerts.py` (`RULES`). If an alert fires too often for normal work, change the number there in
a release and update this page in the same change; `hub/tests_alerts.py` checks that the two match.

### Admin rights changed

**The email** names the person or role (`target`) and the change, for example "given staff status (opens the admin)",
"group added: Moderators", "permission added: Staff hub | post | Can change post" or "user removed: ...". One save in
the admin can send several emails, one per change.

**Normal:** a new moderator or editor set up with a change ticket, someone removed at the quarterly access review
(MAINTENANCE.md), or a leaver's roles emptied.

**Check:**

1. Is there an IT change ticket or a request from the role's owner? If yes, close the alert.
2. Admin, **Log entries**, filtered by content type "user" or "group": the entry at the same time shows which admin
   made the change. **No entry** means the change was made on the server (`shell`, `createsuperuser`), not in the
   admin. Unless an IT administrator did it with a ticket, treat that as an intrusion on the server.
3. Ask the admin who made it, by phone, not through the hub.

**If nobody meant it:** undo it at once (untick Staff status or Superuser, or take the person out of the role), then
follow INCIDENT-PLAYBOOKS.md, "A compromised admin".

### Many failed sign-ins

**The email** shows the last try: `username` (the password form) or `email` (a work account the hub refused), with
`ip`, the network address.

**Normal:** with password sign-in off (the production setting) there are no `sign_in_failed` events at all, and only
an odd `sign_in_rejected` (a guest account, or a re-hire, RUNBOOK.md "Leavers"). Ten in 15 minutes is never normal.

**Check:**

1. See every try in the last hour, with names and addresses:
   ```bash
   docker compose logs --since 1h app | grep -E '"event": "sign_in_(failed|rejected)"'
   ```
2. **`sign_in_failed`** means the password form is on (`ALLOW_PASSWORD_LOGIN=1`). If nobody is using break-glass
   sign-in right now, set it to `0` and run `docker compose up -d`. If the name tried is `breakglass`, change its
   password (RUNBOOK.md, "Rotating keys").
3. **`sign_in_rejected`** with outside email addresses means people from other organisations are trying to get in.
   They are kept out. Check that `ALLOWED_EMAIL_DOMAINS` in `.env` still lists only Supreme's own domains, and look at
   the Entra ID sign-in logs for the app.
4. Most tries from one `ip`: ask the network team to block that address at Supreme's proxy.
5. A `sign_in` for the same name just after the failures means the guess may have worked: follow
   INCIDENT-PLAYBOOKS.md, "A compromised staff account" (or "A compromised admin" for `breakglass`).

### One person keeps hitting the limits

**The email** names the person (`user`) and the last limit hit (`limit`, for example `post`, `comment` or `file`).
Limits on sign-in tries are left out: nobody is signed in yet, and "Many failed sign-ins" covers them.

**Normal:** rare. A communications colleague posting a lot in one busy hour can come close.

**Check:**

1. What did they do? Admin, **Posts** and **Comments**, search their name; or open their profile in the hub. If the
   limit is `search`, someone may be copying the people directory.
2. Call them on a number you already know (not through the hub) and ask whether it was them.
3. Not them, or no answer and the posts look wrong: follow INCIDENT-PLAYBOOKS.md, "A compromised staff account".
   Floods of notifications: "Abuse of push notifications".

### One person is downloading many files

**The email** names the person and the last file. Counted: library files and files attached to posts. Photos and
videos shown in the feed are not counted.

**Normal:** close to never. A new starter reading the whole library, or an editor tidying it, may come near.

**Check:**

1. List what they downloaded:
   ```bash
   docker compose logs --since 24h app | grep '"event": "file_downloaded"' | grep '"user": "name@supreme.co.uk"'
   ```
2. Ask their manager whether it fits their job. If the person may be about to leave, or is taking files they
   shouldn't, **don't contact the person**: follow INCIDENT-PLAYBOOKS.md, "A malicious insider".
3. If the account may be in someone else's hands: "A compromised staff account".

### One person keeps exporting their data

**The email** names the person. "Download my data" gives a zip of everything the person put in the hub, including
their chat messages, so a thief with the account gets it all in one go.

**Normal:** almost never more than once.

**Check:** call the person on a number you already know. If it wasn't them, follow INCIDENT-PLAYBOOKS.md,
"A compromised staff account".

## Alerts from elsewhere

| From | Alerts | Where |
|---|---|---|
| The hub | Disk space low, backups out of date, a scheduled job keeps failing, leaver check failed | MONITORING.md |
| The uptime check | `/healthz` failing | MONITORING.md |
| Supreme's SIEM | Any WARNING or ERROR line in the security log | RUNBOOK.md, "Alerts" |
| Entra ID | Risky sign-ins, sign-ins from new countries, impossible travel (Entra ID Protection) | Supreme's identity team sends these to the same IT queue. The hub can't see where people sign in from. |
| The code host | Dependabot and CodeQL security alerts | MAINTENANCE.md, "Updates to the hub's own code" |

## Test the alerts

Before go-live, after any change to the mail settings, and at the yearly tabletop exercise:

```bash
docker compose exec app python manage.py shell -c "from hub.security import audit; audit('admin_rights_changed', target='alert-test', change='test only, ignore')"
```

"Staff hub: admin rights changed" should reach the IT mailbox within a minute, and the SIEM should page on-call for
the `security_alert` line. If the email doesn't come, test the mail path first:
`docker compose exec app python manage.py sendtestemail --admins`. Record the test in IT's change log.
