# Incident playbooks

Step-by-step playbooks for the incidents most likely to hit One Supreme, plus the contact sheet, status messages, the
yearly tabletop exercise and the post-incident review.

**Start every incident with the breach plan,** `docs/compliance/incident-response-plan.md`. It sets who leads, how
serious the incident is, the first-hour steps that keep evidence and switch things off, which secrets to change, the
72-hour rule for reporting to the ICO, the staff messages and the breach log. This page doesn't repeat any of that.
Each playbook adds only what is particular to one kind of incident, and says "breach plan" where a step is done as
written there.

## Approvals

| Role | Decision |
|---|---|
| Head of IT, Supreme PLC | Signed off (assumed for delivery, 2026-11-20) |
| Data Protection Lead, Supreme PLC | Signed off (assumed for delivery, 2026-11-20) |
| HR Director, Supreme PLC | Signed off (assumed for delivery, 2026-11-20) |
| Internal Communications Manager, Supreme PLC | Signed off (assumed for delivery, 2026-11-20) |

## Contents

1. [A compromised staff account](#1-a-compromised-staff-account)
2. [A compromised admin](#2-a-compromised-admin)
3. [A private post or chat that leaked](#3-a-private-post-or-chat-that-leaked)
4. [A lost or stolen phone](#4-a-lost-or-stolen-phone)
5. [The server or its disk lost](#5-the-server-or-its-disk-lost)
6. [A long outage](#6-a-long-outage)
7. [A malicious insider](#7-a-malicious-insider)
8. [Abuse of push notifications](#8-abuse-of-push-notifications)

Then: [Contact sheet by role](#contact-sheet-by-role), [Status messages](#status-messages),
[Tabletop exercise](#tabletop-exercise) and [Post-incident review](#post-incident-review).

## How to use a playbook

1. Whoever notices something tells the IT service desk (out of hours, the IT on-call number). The incident lead
   takes charge and picks the playbook.
2. Set the level with the breach plan's "How serious is it?" table. Each playbook gives the usual level; if unsure,
   go one higher.
3. **Keep the evidence before anything else:** breach plan, "First hour", step 1. It saves the logs and a copy of the
   database to an `incident-...` file. Rebuilding or recreating containers before that throws the log away.
4. Work down the playbook. Write the time of every step in the timeline (the review template below has the fields).
5. The Data Protection Lead decides about the ICO and about telling the people affected (breach plan).
6. Close with a post-incident review within 10 working days.

**One person's trail** comes up in most playbooks. From the saved incident log, everything one account did:

```bash
grep '"user": "name@supreme.co.uk"' incident-*.log
```

RUNBOOK.md, "Alerts", lists the main events. The ones that matter most here: `sign_in` (with `ip`, the network
address), `push_enabled` (a browser or phone signed up for notifications), `file_downloaded` (library files, by
`name` and `document_id`), `data_exported`, `rate_limited`, `admin_rights_changed`, and the moderation events. Admin,
**Log entries** shows every change made in the admin, by whom. Entra ID's sign-in logs show where the work account was
used. Changes made on the server with `docker compose exec` are **not** in this log: their alerts reach only the IT
mailbox (SECURITY-ALERTS.md, "How an alert reaches a person").

Commands below that start `docker compose` run on the hub's server, in its folder, as in RUNBOOK.md. Replace
`name@supreme.co.uk` with the account's email.

---

## 1. A compromised staff account

**Signs:** an alert from SECURITY-ALERTS.md ("One person keeps hitting the limits", "One person is downloading many
files", "One person keeps exporting their data", or a successful sign-in after "Many failed sign-ins"); colleagues
report odd posts or chat messages from them; Entra ID flags a risky sign-in; the person says they typed their
password into a fake page.

**Usual level:** 2 (high). The Data Protection Lead may lower it to 3 if it was caught at once and nothing was seen.

**Contain, within 30 minutes:**

1. **Entra ID** (Supreme's identity team): block sign-in, revoke sessions, reset the password, and remove the
   account's MFA methods so the person registers them again.
2. **The hub:** Admin, **Users**, search the email, untick **Active**, **Save**. They are signed out at their next
   click, and the hub stops sending them notifications.
3. **Remove every push device on the account.** An attacker may have signed their own browser up for the person's
   notifications, and it would start getting them again once the account is switched back on:

   ```bash
   docker compose exec app python manage.py shell -c "from hub.models import PushSubscription; print(PushSubscription.objects.filter(user__email='name@supreme.co.uk').delete())"
   ```

4. If the person has staff status or a role (Moderators, Communications, Organisation admins, Editors), also follow
   playbook 2.

**Find out what happened:**

5. Keep the evidence (breach plan, "First hour", step 1), then read the person's trail (above). Compare each
   `sign_in` address with where the person really was. A `push_enabled` from an unknown address is the attacker's
   device.
6. **Posts and comments:** Admin, **Posts** and **Comments**, search the person's name. Hide anything harmful with
   "Hide selected from staff". Don't delete it: it is evidence.
7. **Chat:** the admin can't show chats, and nobody reads them without a reason (the DPIA). If the account may have
   sent phishing links or abuse, the Data Protection Lead can allow IT to list only what the account sent during the
   attack. Record that decision in the breach log, then:

   ```bash
   docker compose exec app python manage.py shell -c "from chat.models import Message; [print(m.created_at, m.conversation_id, m.body[:80]) for m in Message.objects.filter(sender__email='name@supreme.co.uk', created_at__gte='2026-11-20T09:00:00+00:00')]"
   ```

8. **Files:** the `file_downloaded` lines (library files, by `name` and `document_id`) and the `data_exported` lines
   show what was taken. Photos and videos in posts, and pictures in chats, aren't logged. The Data Protection Lead
   judges whose data that exposes.

**Recover:**

9. Once Entra ID confirms the account is clean (new password, MFA set up again, the device checked), tick **Active**
   again. The person turns push on again on their own devices (Menu, Settings, Notifications).
10. If the account messaged colleagues, send them [S6: Watch out for fake messages](#s6-watch-out-for-fake-messages).

---

## 2. A compromised admin

**Who counts:** anyone with staff status or superuser; anyone in a role; the `breakglass` account; and anyone who can
reach the server (SSH, the `docker` or `sudo` groups, `.env`, `secrets/`).

**Signs:** an "Admin rights changed" alert nobody expected, especially one with no matching Admin, **Log entries**
line (the change was made on the server, so it reached only the IT mailbox, not the SIEM), or "admin account switched
back on" or "given a new password" for an account nobody is using; a `breakglass` sign-in nobody announced; many
items hidden, restored or deleted at once; unexpected `sso_unlinked` events; backup sets missing from the off-site
share.

**Usual level:** 1 (critical) for superuser, `breakglass` or server access; 2 for a role account without them.

**Contain:**

1. Do steps 1 to 3 of playbook 1 for the account.
2. **Take the rights away:** Admin, **Users**, the person: untick **Staff status** and **Superuser**, empty
   **Groups** and **User permissions**, **Save**. Each change sends an "Admin rights changed" alert; that is
   expected now.
3. **Find everyone else they changed** since the attack began, and undo every change that has no ticket:

   ```bash
   grep '"event": "admin_rights_changed"' incident-*.log
   ```

   Changes made on the server aren't in that log: also search the IT mailbox for "Staff hub: admin rights changed"
   since the attack began. Changes made straight in the database send nothing at all, so then run checks 1 to 8 of
   the quarterly access review (RUNBOOK.md, "Quarterly access review") now.
4. **Superuser, `breakglass` or server access:** treat the whole hub as in the attacker's hands. Follow the breach
   plan's row "Server or admin broken into" (take the hub offline), change every secret in the breach plan's step 3,
   and rebuild on a new server from a clean backup (playbook 5, "after an attack").
5. **Only if step 4 did not take the hub offline:** set `ALLOW_PASSWORD_LOGIN=0` unless break-glass sign-in is
   really in use, run `docker compose up -d`, and change the break-glass password (RUNBOOK.md, "Rotating keys").
   After step 4, never run `docker compose up -d` on the compromised server: it stays switched off as evidence (breach
   plan), and starting it would also start the 05:00 clean-up. Put `ALLOW_PASSWORD_LOGIN=0` and the new break-glass
   password on the rebuilt server instead.
6. If they could push code: check the code host for changes and access since the attack began (GITHUB-SETUP.md).

**Find out what happened:**

7. Admin, **Log entries**, filtered by the admin's name: every change they made in the admin. In their trail: the
   moderation events (`content_hidden`, `content_restored`, `report_resolved`), `sso_unlinked`, `file_downloaded`.
8. Moderators can see reports (with quoted chat messages) and hidden or deleted items. Assume the attacker saw them;
   the Data Protection Lead judges what that means for the people named.

**Recover:**

9. Put back what they hid or deleted: Admin, **Posts** or **Comments**, "Make selected visible again" or "Restore
   selected deleted items". Deleted items can be restored for 30 days; after that only from a backup.
10. Give rights back only after a fresh access review and new credentials.

---

## 3. A private post or chat that leaked

**Signs:** a screenshot of a private group post, a chat or a report turns up outside the hub (another group,
WhatsApp, social media, the press); someone says a post was shown to people it wasn't for.

**Two cases:**

- **The hub showed it to the wrong people** (a bug, or a group with the wrong members or settings). A technical
  breach.
- **Someone who could see it copied it out.** A conduct matter for HR under the house rules. Still a breach if it
  holds personal data.

**Usual level:** 2.

**Contain:**

1. If it exposes personal data, hide the original: Admin, **Posts** or **Comments**, "Hide selected from staff". Don't
   delete it. Chat messages can't be hidden in the admin; ask the sender to delete theirs.
2. **Was the hub showing it to the wrong people?** Check the group: Admin, **Groups and units**, open it. Is it
   private? Are the members right? For news, check the audience on the item. Count who can open the post, moderators
   included (the post's number is in its address):

   ```bash
   docker compose exec app python manage.py shell -c "from hub.models import Post, User; p = Post.objects.get(pk=123); print(p.community, sum(Post.objects.filter(pk=p.pk).viewable_by(u).exists() for u in User.objects.filter(is_active=True)))"
   ```

   Fix the members or the audience. If a bug causes it, take the hub offline (breach plan) until Hivemark AI ships a
   fix with a test that would have caught it.

**Find out what happened:**

3. Who opened it: news that asks for confirmation shows names on "See who has confirmed". Other news records its
   readers only in the database (`PostRead`); listing them needs the Data Protection Lead's OK, as for chat.
   Ordinary posts and chats don't record who read them. **Photos and videos in the post, and pictures in a chat,
   aren't logged either:** nothing says who fetched them. Only library files linked from it show, in
   `file_downloaded` lines (by `name` and `document_id`).
4. A screenshot often shows whose screen it was (their name in the menu, their look). For a chat, the members at the
   time are the only possible sources; reading the chat itself needs the Data Protection Lead's OK, recorded in the
   breach log.
5. If a colleague copied it out, HR leads (`docs/compliance/moderation-procedure.md`).

**Recover and tell:**

6. The Data Protection Lead decides whom to tell, usually the people named in the post (breach plan, message 2).
7. HR or Communications ask wherever it was reposted to take it down.

---

## 4. A lost or stolen phone

**Signs:** a colleague reports it, usually to the service desk.

**Usual level:** 3 (low): single sign-on still protects the hub. 2 if the phone was unlocked with the hub open.

**What is at risk:** a signed-in hub session in the browser or the home-screen app; notifications on the lock screen,
with their text unless the person chose to hide it; files saved in the phone's downloads.

1. **Entra ID:** revoke the person's sessions. For a company phone, also wipe or retire it in Intune. The hub checks
   with Microsoft at least every 15 minutes while it is in use, so the hub session ends within 15 minutes.
2. **Stop notifications reaching the phone.** List the person's devices, then delete the lost one (or all of them):

   ```bash
   docker compose exec app python manage.py shell -c "from hub.models import PushSubscription; [print(p.pk, p.created_at, p.device[:70]) for p in PushSubscription.objects.filter(user__email='name@supreme.co.uk')]"
   docker compose exec app python manage.py shell -c "from hub.models import PushSubscription; print(PushSubscription.objects.filter(pk=42).delete())"
   ```

   The person turns push on again on their new phone.
3. If Entra ID can't be reached quickly and the phone was unlocked, untick **Active** for the person in the hub admin
   until it can.
4. Read the person's trail from the time of the loss. A `sign_in`, `file_downloaded` or `push_enabled` from an
   unknown address means the phone is being used: follow playbook 1.
5. A personal phone with no company management can't be wiped: note that in the breach log, and ask the person to
   change their Microsoft password.

No hub secrets need changing.

---

## 5. The server or its disk lost

Restore from backup. BACKUPS.md has every command; this playbook is the order of work around it.

**Signs:** the uptime check fails (MONITORING.md); the server doesn't start; a failed disk; the virtual machine
deleted; ransomware on the server.

**Usual level:** 1 if an attack caused it (ransomware, deletion by an intruder). Otherwise it is an outage, not a
breach, but still keep a timeline.

**Targets:** at most 24 hours of data lost; back within 4 hours on the same server, or 1 working day on a new one
(BACKUPS.md, "Recovery targets").

1. **Tell staff** the hub is offline (breach plan, message 1). Then [S2](#s2-still-working-on-it) every 2 hours.
2. **Choose:**
   - The server is fine but data is damaged: BACKUPS.md, "Restore on the same server".
   - The server is gone: BACKUPS.md, "Restore onto a new server".
   - **After an attack**, or any doubt: always a new server, from a set made before the attack, with new secrets
     (BACKUPS.md, "After a security incident"). Keep the old server switched off but intact, for evidence.
3. **From IT's vault:** `.env` and the backup key. If the Entra certificate (`secrets/entra.pem`) was lost with the
   server, make and upload a new one (ENTRA-SETUP.md, steps 2 and 3); no one can sign in until then.
4. Restore and check, as in BACKUPS.md. Then run the clean-up so data past its retention period isn't brought back
   (breach plan, "Recover", step 2), and redo the deletions made since the backup (BACKUPS.md, step 6).
5. Point Supreme's proxy at the server, check `/healthz` gives `200`, and check the uptime monitor is green again.
6. **Push:** with the same `VAPID_*` keys from the vault, push keeps working. With new keys, send
   [S7](#s7-turn-push-notifications-off-and-on-again).
7. **All clear** (breach plan, message 4), adding: "Anything posted, sent or uploaded after [time of the backup] was
   lost. Please post it again."
8. The next morning, check the backup ran ("Backups OK" in `docker compose logs scheduler`).
9. If a disk left the building whole (stolen, or returned without wiping), the Data Protection Lead decides whether it
   is a breach. The server's disks are encrypted (INSTALL.md), which usually makes it one not to report.

---

## 6. A long outage

**Long** means staff can't use the hub for more than an hour in working hours or on a warehouse shift.

**Signs:** the uptime check alerts on-call; staff report it; Microsoft 365 service health shows an Entra ID problem.

**Usual level:** not a breach on its own. It becomes one if data is lost or an attack caused it.

**First 15 minutes:** on-call opens `/healthz` from outside, runs `docker compose ps` and reads the logs
(RUNBOOK.md). Send [S1](#s1-we-know-about-it).

**Find the layer:**

| What you see | Likely cause | Go to |
|---|---|---|
| `/healthz` answers `200`, but nobody can sign in | Entra ID, or the hub's Entra certificate | Microsoft 365 service health; ENTRA-SETUP.md, "When it goes wrong" |
| `503` with `"database": "down"` | Postgres stopped, or its disk is full | `docker compose ps db`, `docker compose logs db` |
| `503` with `"disk": "full"` | The disk is full; uploads are paused | MONITORING.md, the disk alert |
| `502`, `504` or no answer | The app or nginx is down, or the server or network | `docker compose ps`, `docker compose up -d`; Supreme's network team for the proxy |
| Pages very slow | The server is short of CPU or memory | `docker stats` |
| Just after an upgrade | The new release | RUNBOOK.md, "Upgrading to a new release", rolling back |

**At 1 hour:** if it isn't fixed, call Hivemark AI support (contact sheet) and send [S2](#s2-still-working-on-it)
with the time of the next update.

**Entra ID down:** nobody can sign in, and people already signed in lose the hub at its next 15-minute check with
Microsoft. Nothing in the hub can work round that for staff. Break-glass sign-in (RUNBOOK.md) is for admins with
something that can't wait.

**At 4 hours** on the same server: if it can't be fixed, start playbook 5 onto a new server.

**When it is back:** breach plan, message 4. Hold a review for any outage over 4 hours, or the second one in a month.

---

## 7. A malicious insider

**Who:** a colleague, moderator, admin or IT person using access they really have, to do harm: copying files before
they leave, harvesting the staff directory, reading reported content for gossip, posting others' personal data,
deleting library files, or giving themselves more rights.

**Signs:** "One person is downloading many files", "One person keeps exporting their data", "One person keeps hitting
the limits" (searches) or an unexpected "Admin rights changed" (SECURITY-ALERTS.md); HR tells IT someone is under
investigation or about to be dismissed; colleagues report it.

**Usual level:** 2 ("a moderator or admin misusing access" in the breach plan); 1 if they have server access.

**The rule:** HR and the Data Protection Lead lead; IT supports. Don't warn or confront the person until the
evidence is safe and the moment to remove access is agreed. Talk by phone or email, never in the hub.

1. The incident lead, the HR Director and the Data Protection Lead agree the plan. Keep the group small.
2. **Keep the evidence quietly:** breach plan, "First hour", step 1. The person can't see this happen.
3. **Their trail** (above): `file_downloaded`, `data_exported`, `rate_limited` with `limit` `search`,
   `admin_rights_changed` naming them, `document_deleted`, `folder_deleted`, `content_hidden`, `group_member_added`,
   `chat_member_added`. Admin, **Log entries**, filtered by their name. For HR's case file, save pages as PDF straight
   into the case folder, never into email (moderation procedure).
4. **Remove all access at the agreed time, together:**
   - Entra ID: block sign-in and revoke sessions.
   - The hub: untick **Active** and **Superuser**, empty their **Groups** and **User permissions**, delete their push
     devices (playbook 1, step 3). Leave **Staff status** as it was: RUNBOOK.md, "Leavers", keeps it ticked so their
     account and their entries in the moderation log are kept. Each change sends an "Admin rights changed" alert,
     which is expected. Anyone who later switches the account back on or sets its password sets one off again.
   - The server and the code: SSH key, `docker` and `sudo` groups, code host access.
   - Secrets they could read: change them (MAINTENANCE.md, "When to rotate each secret"), including the break-glass
     password if they knew it.
5. **Undo damage:** restore hidden or deleted posts and comments (playbook 2, step 9). Deleted library files leave the
   hub's disk at once: get them back from the newest backup set made before the deletion, with Hivemark AI's help
   (BACKUPS.md).
6. The Data Protection Lead judges what personal data left and whom to tell. HR decides on the disciplinary side
   and on asking for copies back or a signed promise they are deleted. Theft of company data can be reported to the
   police (contact sheet).

---

## 8. Abuse of push notifications

**Two kinds:**

- **Through the hub:** an account (taken over, or a colleague) flooding people with notifications or sending
  misleading ones: many posts, @mentions, news (which notifies its whole audience) or event invitations.
- **Around the hub:** someone with the push private key (`VAPID_PRIVATE_KEY`) and a copy of the device list (from the
  database) sends messages straight to staff phones. They can write any text. Tapping one still only opens a page of
  the hub, because the hub's notification code refuses other sites, but the text itself can send people to a fake
  site.

**Signs:** staff report odd or repeated notifications; "One person keeps hitting the limits"; notifications that match
nothing in the hub (the second kind).

**Usual level:** 3 for a flood from one account caught quickly; 2 for misleading messages, and for the second kind,
which also means the database was copied (playbook 2, and the breach plan's level 1).

**Through the hub:**

1. Stop the account: playbook 1 if taken over, playbook 7 if a colleague. Take them out of the Communications role if
   they have it.
2. **Stop what is still queued.** Notifications go to phones for up to 10 minutes after they are made, and into the
   next morning's email digest. This marks the account's ones as already sent, and keeps them as evidence:

   ```bash
   docker compose exec app python manage.py shell -c "from django.utils import timezone; from hub.models import Notification; n = Notification.objects.filter(actor__email='name@supreme.co.uk'); now = timezone.now(); print(n.filter(pushed_at=None).update(pushed_at=now), n.filter(emailed_at=None).update(emailed_at=now))"
   ```

3. Hide the posts (Admin, **Posts**, "Hide selected from staff").
4. If the messages asked people to do something, send [S6](#s6-watch-out-for-fake-messages).

**Switch push off for everyone** (any kind): empty `VAPID_PRIVATE_KEY` in `.env` and run `docker compose up -d`.
Notifications still appear in the hub. Putting the same key back turns push on again with nothing for staff to do.

**Around the hub:**

1. Make new push keys and delete every device (RUNBOOK.md, "Rotating keys", push keys).
2. That isn't enough on its own: each phone's old sign-up stays open at Apple's, Google's or Mozilla's push service
   until the phone turns it off. Send [S7](#s7-turn-push-notifications-off-and-on-again) to all staff by email and in
   the hub, and [S6](#s6-watch-out-for-fake-messages) with it.
3. Treat it as a copied database: playbook 2 and the breach plan.

---

## Contact sheet by role

Print this page section, write the phone numbers in by hand from IT's on-call list, and keep copies where they can be
reached without the hub, email or the network: the IT office, the warehouse shift manager's office, and at home for
the incident lead and the IT on-call engineer. IT checks it at each quarterly access review (MAINTENANCE.md).

| Role | Held by | When to call | Phone |
|---|---|---|---|
| IT service desk | Supreme IT | First contact, working hours | |
| IT on-call engineer | Supreme IT rota | First contact out of hours; uptime and paging alerts | |
| Incident lead and security owner | Head of IT (deputy: IT on-call engineer) | Every incident | |
| Data Protection Lead | Supreme's Data Protection Lead | Any personal data involved; the ICO decision | |
| HR | HR Director (deputy: HR Business Partner) | Staff involved, insiders, welfare | |
| Communications | Internal Communications Manager (also lead moderator) | Any staff message; the press | |
| Identity team | Supreme IT, Entra ID administrators | Blocking accounts, revoking sessions, Entra alerts | |
| Network team | Supreme IT, proxy and firewall | Blocking addresses, pointing the proxy at a new server | |
| Storage team | Supreme IT, off-site backup share | Snapshots of the share, a new share | |
| Supplier | Hivemark AI support lead | Bugs, fixes, help investigating (data processing agreement: they tell Supreme within 24 hours of finding a problem) | |
| Microsoft | Microsoft 365 admin centre, support | Entra ID outages | |
| Cyber insurer | Per Supreme's policy | Within the policy's notice period, often 24 to 72 hours | |
| Legal adviser | Supreme's solicitors | Insider cases, press, regulators | |
| ICO | ico.org.uk, or 0303 123 1113 | Reportable breaches, within 72 hours (Data Protection Lead only) | 0303 123 1113 |
| Police | Action Fraud, 0300 123 2040 (Police Scotland: 101) | Theft of data, extortion, an attack on the server | 0300 123 2040 |
| NCSC | ncsc.gov.uk, report an incident | A serious attack | |

## Status messages

The breach plan has the main messages: the hub offline (1), telling the people affected (2), the supplier's notice
(3) and the all clear (4). Use those first. These cover the updates in between and the cases they don't.

**Where to send them:** all-staff email and Teams; in the warehouse, the shift managers read them out at the shift
briefing and write them on the board, because many warehouse staff only see the hub on their phones. Post in the hub
as well only if it is working and isn't the problem. Communications sends them; the incident lead approves the facts.
Keep them short, say only what is known, and always give the time of the next update.

### S1: We know about it

> Subject: One Supreme isn't working right now
>
> One Supreme isn't working for [everyone / some people] at the moment. We know and we're on it. Your other work
> systems are fine. Next update by [time].
>
> IT Service Desk

### S2: Still working on it

> Subject: One Supreme: update at [time]
>
> One Supreme is still unavailable. [One sentence on what we're doing, for example: we're moving it to a spare
> server.] We expect it back [by time / later today / we don't know yet]. Next update by [time]. For anything urgent,
> use email or speak to your manager.
>
> IT Service Desk

### S3: Part of the hub is switched off

> Subject: One Supreme: [push notifications / uploads / sign-in with a password] switched off for now
>
> We've switched off [feature] in One Supreme while we fix a problem. Everything else works as usual. [What people
> can do instead, for example: open the hub to see your notifications.] We'll tell you when it's back.
>
> IT Service Desk

### S4: Planned maintenance

Send 2 working days before, and again 1 hour before.

> Subject: One Supreme will be offline on [day] from [time] to [time]
>
> We're updating One Supreme on [day] between [time] and [time]. You won't be able to use it then. Nothing you've
> posted will be lost. [If needed: You may need to sign in again afterwards.]
>
> IT Service Desk

### S5: Please sign in again

> Subject: One Supreme: please sign in again
>
> To keep the hub safe, we've signed everyone out. Open One Supreme and sign in with your work account as usual. If
> it asks you to sign in to Microsoft, check the address starts with https://login.microsoftonline.com before you type
> anything.
>
> IT Service Desk

### S6: Watch out for fake messages

> Subject: Watch out for fake messages on One Supreme
>
> On [date], [one sentence, for example: someone else used a colleague's account and sent links in chat]. If you got a
> message or notification asking you to [what it asked], don't open the link and don't type your password. If you
> already did, change your Microsoft password now and tell the IT Service Desk. One Supreme and IT will never ask for
> your password in a message or notification.
>
> IT Service Desk

### S7: Turn push notifications off and on again

> Subject: One Supreme: please switch notifications off and on again
>
> We've changed the keys that send One Supreme notifications. On every phone or computer where you get them, open the
> hub, go to Menu, Settings, Notifications, choose "Turn off for this device", then "Turn on for this device". Until
> you do, you won't get notifications from the hub, and anything that still arrives in its name isn't from us.
>
> IT Service Desk

**At the shift briefing** (read out, 30 seconds): "One Supreme is [down / partly off] because [one plain reason]. IT
is on it and expects it back [when]. Your shift details are on the board as usual. If you get a strange message or
notification from the hub, don't tap it: tell your shift manager."

## Tabletop exercise

Once a year, in October (MAINTENANCE.md), and after any big change to the hub or the team. 90 minutes, round a table
or on a call. Nothing live is touched except the alert test at the end.

**Who:** everyone in the contact sheet's first seven rows, or their deputies. A facilitator runs it: the Head of IT,
or Hivemark AI's support lead in a year the Head of IT plays the incident lead. One person keeps notes in the
post-incident review template.

**Bring:** the breach plan, this page, the contact sheet, BACKUPS.md, a clock everyone can see.

**Rules:** answer as you would on the day, with the people and tools you really have. "I'd look it up" is fine if you
can say where. The facilitator reads each inject, then asks its questions; move on at the time shown even if the
discussion isn't finished, and note what was left open.

**Scenario: "Our database leaked".**

| Time | Inject (read out) | Questions |
|---|---|---|
| 0:00 | Monday 08:40. The service desk gets an email from an outside address with a spreadsheet of 40 staff: names, job titles, mobile numbers and birthdays, "from your intranet". It asks for money, or the full list goes public. | Who leads? What level is this (breach plan)? Who is called, and how, if email might be watched? What is the very first thing done on the server? When does the 72-hour clock start? |
| 0:15 | Unread in the IT mailbox since Saturday 02:13: "Staff hub: admin rights changed", a moderator's account made a superuser. Admin, Log entries has no line for it, and the SIEM has no `security_alert` line for it either, so nobody was paged. | What do the missing lines tell you? Which playbook now? Who decides to take the hub offline, and what do staff hear (which message)? Which secrets must change? Should the IT mailbox be read at weekends? |
| 0:30 | The storage team says the last three nightly sets are missing from the off-site share. | Which backup can be trusted? Same server or new? How long until the hub is back (BACKUPS.md targets)? What about the backup key? |
| 0:45 | A journalist calls Communications. On the warehouse early shift, people ask the shift manager why the hub is down. | What is said, by whom, approved by whom? Pick the messages. What is said at the shift briefing? |
| 1:00 | Tuesday 16:00. Some facts are still unknown. | Does the Data Protection Lead report to the ICO, and by when exactly? What goes in the report? Are the 40 people told, and how? Is the insurer told? The police? |
| 1:15 | Wrap up. | What went well? Where did we hesitate or not know? Actions, each with an owner and a date. |

**Other years**, take turns with: a moderator's account taken over that posts a staff list (the breach plan's
example); a manager's stolen phone showing notifications on its lock screen; a leaver downloading the library the
week before they go; notifications telling staff to "confirm your password" on a fake site.

**At the end:** run the alert test in SECURITY-ALERTS.md, "Test the alerts" (a change in the admin), and check that
the emails arrive and the on-call engineer is paged. Then write up the exercise with the review template below, and
file the actions like an incident's.

## Post-incident review

Within 10 working days of every level 1 or 2 incident, every outage over 4 hours, and every tabletop exercise. The
incident lead runs it; everyone who took part comes. The breach plan's "learn" section sets the rule: **no blame.**
Ask what in the systems, tools and instructions let it happen or slowed us down, never who is at fault.

Copy this into IT's incident folder and fill it in:

```text
Incident review: [short name]                         Reference: [breach log reference, if any]
Date of review:          Run by (role):           Present (roles):
Level (breach plan):     Playbook(s) used:

1. Summary, in three sentences: what happened, to whom, and how it ended.

2. Timeline (times in UK time; from the timeline kept during the incident)
   - [time] First sign (what, seen by which role)
   - [time] Service desk told
   - [time] Evidence kept (breach plan, first hour, step 1)
   - [time] Contained (what was switched off)
   - [time] Data Protection Lead's decision on the ICO (reported at / not reported, because)
   - [time] Staff told (which message)
   - [time] Back to normal

3. Impact: people affected (rough number), data involved, time the hub was down, data lost.

4. Causes: what made this possible, and why it wasn't stopped or seen sooner. Keep asking "why" until the answer is
   something we can change.

5. What helped.

6. What slowed us down or confused us (a missing step, a wrong command, an alert nobody saw, a contact missing).

7. Actions
   | # | Change | Where (code with a test / playbook / breach plan / DPIA / training) | Owner (role) | Due | Done |
   |---|--------|------|------|-----|------|

8. Sign-off: incident lead, Data Protection Lead (closes the breach log entry).
```

**Feed it back:** every action is tracked to done at the next monthly patching day (MAINTENANCE.md). A fix in the
hub's code comes with a test that fails without it. Update this page, SECURITY-ALERTS.md, the breach plan or the DPIA
in the same change when the review shows they were wrong or missing something.
