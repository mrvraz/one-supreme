# Maintenance

The routine work that keeps One Supreme safe for its whole life: the calendar, how updates are handled, when each
part of the stack stops getting security fixes, and when to change each secret. This page says **when** and **who**.
The commands are in RUNBOOK.md and BACKUPS.md.

## Approvals

| Role | Decision |
|---|---|
| Head of IT, Supreme PLC | Signed off (assumed for delivery, 2026-11-20) |
| Data Protection Lead, Supreme PLC | Signed off (assumed for delivery, 2026-11-20) |
| Delivery lead, Hivemark AI | Signed off (assumed for delivery, 2026-11-20) |

**Who:** "IT" is Supreme IT. The **security owner** is the Head of IT. **Hivemark AI** maintains the hub's code and
makes its releases. Every task below goes into IT's change log when done: the date, who, and what changed.

## The calendar

| When | What | Who | How |
|---|---|---|---|
| Every night, by itself | Security updates for the server; backup at 02:00 UTC; clean-up, leaver check and digest at 05:00 UTC | Nobody: an alert comes if one fails | INSTALL.md step 1, BACKUPS.md, MONITORING.md |
| Every working day | Read the IT mailbox for hub alerts | IT service desk | SECURITY-ALERTS.md, MONITORING.md |
| Every Monday | Review the week's update pull requests and merge the ones whose checks pass | Hivemark AI | [Updates to the hub's own code](#updates-to-the-hubs-own-code) |
| Every week | Check the scheduler is alive | IT | MONITORING.md, "When the scheduler itself is stuck" |
| Second Wednesday of each month | **Patching day:** the server, the containers, the Python libraries check, and the hub release with that month's merged updates. Then chase open actions from incident reviews | IT, with Hivemark AI's release | RUNBOOK.md, "Monthly patching" and "Upgrading to a new release" |
| Within 48 hours of the news | A flaw that is being actively exploited, in anything the hub runs on | IT and Hivemark AI | [How fast a fix goes in](#how-fast-a-fix-goes-in) |
| Every month | Moderation review | Lead moderator | `docs/compliance/moderation-procedure.md`, "Monthly review" |
| First week of January, April, July, October | **Access review**, and check the contact sheet's numbers. It also catches rights changed straight in the database, which send no alert | Security owner and an IT administrator | RUNBOOK.md, "Quarterly access review"; INCIDENT-PLAYBOOKS.md, "Contact sheet by role"; SECURITY-ALERTS.md |
| The same week | Restore test | IT | BACKUPS.md, "Restore test, every quarter" |
| The same week | Check the deletion jobs ran | IT and the Data Protection Lead | [Deletion check](#deletion-check) |
| January | Change `SECRET_KEY` and the break-glass password | IT | [When to rotate each secret](#when-to-rotate-each-secret) |
| A month before the Entra certificate's end date | New Entra certificate | IT | RUNBOOK.md, "Rotating keys" |
| October | Tabletop exercise | Head of IT | INCIDENT-PLAYBOOKS.md, "Tabletop exercise" |
| November | **DPIA review**, with the record of processing, the privacy notice and the retention periods | Data Protection Lead | `docs/compliance/dpia.md`, section 8 |
| November | Review the vendors and services, and this page's end-of-life table | Head of IT and the Data Protection Lead | [Vendors and services](#vendors-and-services), [End of life](#end-of-life) |
| Once a year, and after big changes | Full restore onto a spare server | IT | BACKUPS.md, "Once a year" |
| Once a year, and after big changes | Independent penetration test; fix what it finds before the next release | Head of IT commissions it; Hivemark AI fixes | `docs/security/PENTEST-REPORT.md` for the last one |

A "big change" is a new kind of data, a new outside service, a new way to sign in, or a move to a new server.

## Updates

### Updates to the hub's own code

The hub pins every Python library to an exact version (`requirements.txt`) and builds from a pinned Python image
(`Dockerfile`). Nothing changes by itself.

1. **Every Monday,** Dependabot opens update pull requests on the code host: Python libraries, the Docker base image
   and the CI actions, grouped so there are few (`.github/dependabot.yml`). A new version waits 7 days before it is
   proposed, so a hijacked release is usually pulled first.
2. Each one runs the same checks as any change: tests, Django's deploy checks, the dependency audit, the secret scan
   and CodeQL (GITHUB-SETUP.md). Hivemark AI merges the ones that pass within the week, and they go live on the next
   patching day as a release, with release notes.
3. **Security alerts** from Dependabot or CodeQL go to the repository owners by email (GITHUB-SETUP.md). Hivemark AI
   answers within 1 working day with how fast the fix goes in (below).
4. **Big version jumps are projects, not weekly updates:** Django 5.2 to 6.2, Python 3.12 to a newer one, Postgres
   17 to a newer one. Dependabot is set not to propose them. Each gets its own release, tested, with its steps in
   the release notes and a backup first. The plan for each is in the end-of-life table.
5. **New libraries:** only when Python or a library the hub already has can't do the job. Before adding one, check it
   is maintained, widely used, has a clear licence and no install scripts, and that the name is exactly right (not a
   look-alike). A second reviewer approves it. It is pinned like the rest.

### How fast a fix goes in

| How bad | Examples | Live by |
|---|---|---|
| Being exploited now | On the NCSC's or CISA's list of exploited flaws; a Django security release for a flaw already being used | 48 hours |
| Critical or high | A Django security release rated high; a flaw that lets someone in without signing in, or read others' data | 7 days |
| Moderate or low | Everything else | The next patching day |

The same rule covers the server and the images: an urgent fix is installed the same way as on patching day
(RUNBOOK.md, "Monthly patching"), just sooner.

**Where the news comes from:** the IT mailbox is subscribed to Django's security announcements (the django-announce
list), the Python security announcements list, PostgreSQL's announcements and Ubuntu's security notices. Dependabot
alerts and the monthly `pip-audit` (RUNBOOK.md) catch the Python libraries.

## End of life

Upgrade before security fixes stop, not after. Dates are from each project's published schedule; check them each
November.

| Part | Version in use | Security fixes until | Plan |
|---|---|---|---|
| Django | 5.2 LTS | April 2028 | Move to Django 6.2 LTS (due April 2027) by January 2028 |
| Python | 3.12, in the `python:3.12-slim` image | October 2028 | Move with Django 6.2, by January 2028, to the newest Python that Django 6.2 supports |
| Debian, the base of the `python:3.12-slim` image | 13 "trixie" | 9 August 2028 (then Debian LTS to 30 June 2030) | Comes with each new image; check it is still a supported Debian when Python moves |
| PostgreSQL | 17, the `postgres:17` image | 8 November 2029 | Move to the newest major version by May 2029. It needs a dump and restore, so it comes as a release with its own steps |
| nginx | the stable branch, `nginx:stable-alpine` | A new stable branch each spring | Moves by itself with the monthly `docker compose pull` |
| The server | Ubuntu 24.04 LTS (INSTALL.md) | April 2029 | Upgrade to Ubuntu 26.04 LTS, or build a new server and restore onto it (BACKUPS.md), by January 2029 |

To see what an image really runs on: `docker compose run --rm --no-deps app cat /etc/os-release` (and `db` for
Postgres).

## When to rotate each secret

Change a secret on its schedule, **and at once** whenever it may have been seen by someone who shouldn't have it,
including anyone who could read it and leaves (RUNBOOK.md, "Leavers"). After a security incident, change everything
the attacker could have reached (the breach plan, step 3). The commands are in RUNBOOK.md, "Rotating keys", unless
the table says otherwise.

| Secret | Where it lives | On a schedule | At once when |
|---|---|---|---|
| `SECRET_KEY` | `.env` | Every January | Anyone who could read `.env` leaves; any chance it leaked |
| Entra certificate | `secrets/entra.pem` and the Entra app | A month before its end date (at least yearly) | Anyone with `sudo`, the `docker` group or user 1000 leaves; the file may have been copied |
| Entra client secret | Should not exist: the hub uses the certificate | - | One is found in the app registration: delete it (ENTRA-SETUP.md) |
| Break-glass password | IT's password manager | Every January, and after every use | Anyone who knew it leaves |
| `DB_PASSWORD` and `DB_OWNER_PASSWORD` | `.env` and Postgres | - | Anyone who could read `.env` leaves |
| Backup key (`BACKUP_KEY_FILE`) | The server and IT's vault | - (old backup sets need the old key) | The server was broken into: BACKUPS.md, "After a security incident" |
| `EMAIL_HOST_PASSWORD`, `TRANSLATE_API_KEY` | `.env` | When their owners rotate them | They may have leaked |
| Push keys (`VAPID_*`) | `.env` | - (every device has to sign up again) | The private key leaked, or the database was copied: INCIDENT-PLAYBOOKS.md, playbook 8 |
| IT administrators' SSH keys | The server | Checked at each access review | Their owner leaves or loses the device |
| Code host access and the server's read-only key | The code host | Checked at each access review | Their owner leaves; secret scanning finds a key (GITHUB-SETUP.md) |

## Deletion check

Each quarter, in the access review week, check that old data really goes:

1. The clean-up ran every day: in the SIEM, one `retention_purge` line a day for the last 90 days, with counts.
   On the server: `docker compose logs --since 48h scheduler | grep retention_purge`.
2. The retention periods are the ones agreed: `docs/compliance/data-inventory-and-retention.md` has the command
   that prints them.
3. Backups: the oldest set on the off-site share is no more than 8 weeks old (BACKUPS.md, "What is kept"), so
   deleted data leaves the backups too.

Anything wrong is fixed before the review is signed off, and the Data Protection Lead is told.

## Vendors and services

Each November, list every service that receives hub data or can reach the server, and switch off any that is no
longer used. Each one still in use must be in the record of processing (`docs/compliance/record-of-processing.md`).

| Service | What it gets | Owner |
|---|---|---|
| Supreme's SMTP relay | Digest emails and alerts | Supreme IT |
| Microsoft Entra ID | Sign-ins, the leaver check | Supreme IT |
| Push services (Apple, Google, Mozilla, Microsoft) | Encrypted notifications they can't read | Supreme IT (outbound firewall) |
| Translation server, if `TRANSLATE_URL` is set | The text of posts people translate | Supreme IT |
| Supreme's SIEM | The security log | Supreme IT |
| Off-site backup storage | Encrypted backup sets | Supreme IT |
| The code host | The code, never staff data | Supreme IT and Hivemark AI |
| Hivemark AI | Access to help with incidents, under the data processing agreement | Head of IT |
