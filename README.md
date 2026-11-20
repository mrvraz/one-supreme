# Staff Hub

A private social network and intranet for one company's employees: a feed, news, chat, groups and teams, events, files, a knowledge base, onboarding journeys, internal jobs and a people directory. Only people with a company account can sign in. Built by Hivemark AI for Supreme PLC (about 500 staff), and white-labelled so it can be resold.

The screens follow the Hiveshire **Daylight** (light) and **Daylight Dark** looks. Everyone picks Light, Dark or "same as my device" under Settings, Appearance.

## What's in version 2

| Area | What staff can do |
|---|---|
| Sign-in | Single sign-on with their Microsoft (Entra ID) or Google work account. Only the company's email domains get in, so directory guests are kept out. People who leave lose access within 15 minutes of IT disabling their account. |
| Feed | Post text with simple formatting (bold, italic, lists, links), up to 10 photos or videos (250 MB in total), to everyone or to a group or team. Six reactions, comments with one level of replies, reactions and a picture on comments, @mentions, editing, following a post. Filter by everything, company-wide or my groups, and by type; sort by newest or recent activity. |
| Polls | Ask a question with 2 to 10 answers and an optional closing time. Results show once you've voted. |
| Scheduling | Posts, polls and news can go out later; they wait under Menu, Scheduled posts. |
| Pinned posts | Moderators (and group admins, in their group) pin posts to the top, with a coloured tag by type. Announcements are pinned and alert everyone. |
| News | People with the "Can publish news" permission write news with a title and cover, for everyone or chosen teams and groups, as a draft or scheduled. Readers filter by unread. Important news can ask readers to confirm; only then does the author see who has and hasn't. For other news they see totals only. |
| Chat | One-to-one and group chats with pictures, unread counts, mute, leave, delete and report a message. Old messages can be removed after `CHAT_RETENTION_DAYS`. |
| Groups | Public groups anyone can join, and private groups people join by invitation or by asking. Group admins edit the group and cover, invite, approve requests, remove members and appoint other admins. Each group has its own files and featured items. |
| Organisation | Business units, departments, locations and teams, placed by admins (staff don't join or leave them). News and posts can target them, and the directory filters by them. |
| Events | Create, edit and RSVP. Reminders at the times each person chooses (per event too), "Add to calendar" for Outlook, Google and Apple. |
| People | Searchable directory with profile, cover photo, pronouns, languages and work phone; an online dot people can switch off. Opt-in birthdays (day and month only) and work anniversaries. |
| Files | Company documents in folders, featured documents and links, and per-group files. Only signed-in staff can download. |
| Knowledge base | Articles in categories, with legal documents also listed under About. |
| Journeys | Step-by-step onboarding (or any programme) given to everyone or chosen teams. Each person ticks off steps; editors see progress. |
| Jobs | Internal vacancies. Staff say "I'm interested" with a note, and the recruiter is told. |
| Alerts | In-app alerts, push notifications on phones and computers, and a daily email digest. Each person picks which kinds of alert come by push and by email, sets quiet hours or quiet weekends, can pause everything with Do not disturb, and chooses whether push shows the text or just "something new". |
| Search | One search across people, news, posts, groups, events, files, knowledge base, journeys and jobs. It only finds what the person may see. |
| Translation | "See translation" under posts and comments, when a self-hosted LibreTranslate server is set. |
| Insights | Totals for admins with the "Can view usage figures" permission: active people, posts, comments and how far news reached. No individual tracking. |
| Moderation | Anyone can report a post, comment, chat message or person. Moderators see reports in the admin, hide content in one click, and restore deleted items. Every moderator action and every deletion lands in a read-only audit log. |
| Evidence | Deleted posts and comments vanish at once but are kept for 30 days, and for as long as a report about them is open, so nobody can destroy evidence before HR sees it. |
| Phones | Works in any phone browser and can be added to the home screen like an app, with a floating tab bar on small screens. |
| Privacy | Photos are re-encoded and videos are copied without metadata, so GPS location and device details are stripped. Uploads are only served to signed-in staff who may see them. |
| Data protection | Everyone accepts the house rules (with a data notice) on first sign-in, and again when they change. Anyone can download their own data, from every section, as a zip. Old alerts, deleted content and (optionally) old posts, chat messages and leavers' accounts are removed automatically. |
| Abuse limits | Per-person limits on posts, uploads, comments, reports, events and groups; request limits in nginx; uploads pause and IT is emailed before the disk fills. |
| Leavers | Signed out within 15 minutes of IT disabling them, and switched off in the hub by a nightly check against Entra ID. Accounts are tied to Microsoft's permanent user ID, so someone whose email changes keeps their account. |
| Security log | Sign-ins, failed sign-ins, deletions, moderation, limits hit, exports and deactivations are written as JSON lines for Supreme's security monitoring (SIEM). |

`docs/FEATURE-PLAN.md` compares these features with the app Supreme uses today.

## How it's built

- **Django 5.2 LTS** (security fixes until April 2028) with server-rendered pages and a little plain JavaScript. No front-end build step.
- **Postgres** in production; SQLite for local development.
- **mozilla-django-oidc** for single sign-on (generic OpenID Connect, so Entra ID, Google or Okta all work).
- **Web Push** (the browser standard) for push notifications, so no Apple or Google developer account is needed. On iPhones, push works once the hub is added to the home screen (iOS 16.4 or later).
- **Docker Compose** for Supreme's servers: Postgres, the app (gunicorn), the scheduler and nginx.
- **ffmpeg** strips metadata from videos (installed in the Docker image; locally, video uploads are refused without it).
- The Django admin is the moderation desk; there is no separate admin app to maintain.

Code map:

- `hub/`: the core.
  - Data and pages: `models.py` (data), `views.py` (feed, posts, people, groups, events), `news.py`, `account.py` (alerts, settings, search, push, about), `forms.py`.
  - Publishing and delivery: `publishing.py` (who is told), `push.py` (Web Push), `tasks.py` (scheduled posts and reminders).
  - Content safety: `richtext.py` (safe formatting), `media.py` (upload checks).
  - Access and security: `auth.py` (SSO rules), `security.py` (audit log, headers, house rules, limits), `admin.py` (moderation).
  - Glue: `plugins.py` (how the other apps plug in).
- `chat/`, `library/` (files, featured items, knowledge base), `journeys/`, `jobs/`: one app each, plugging into the menu, search, data export and clean-up through `hub/plugins.py`.
- `hub/templates/hub/` and `hub/static/hub/`: pages, styles (`app.css` holds both looks), scripts and the push service worker.
- `config/settings.py`: all settings come from environment variables.

Scheduled jobs (the `scheduler` service runs `python manage.py scheduler`; times are UTC):

| Command | When | What it does |
|---|---|---|
| `tick` | every minute | Publishes scheduled posts and news when their time comes, sends event reminders, and sends push notifications. |
| `check_disk` | hourly | Emails `ADMIN_EMAILS` when the disk is over 85% full. Uploads pause at 95%. |
| `send_digests` | daily, about 05:00 | The email summary of unread alerts, with only the kinds each person wants by email. Skipped while someone has Do not disturb on. |
| `sync_directory` | daily | Switches off accounts removed or disabled in Entra ID. Refuses to switch off more than a fifth of accounts at once, in case of a misconfiguration, and emails `ADMIN_EMAILS` whenever it fails. `--dry-run` shows who would go. |
| `purge` | daily | Removes deleted content after 30 days (unless under an open report), alerts after 90 days, posts after `POST_RETENTION_DAYS`, chat messages after `CHAT_RETENTION_DAYS`, and leavers' accounts `LEAVER_RETENTION_DAYS` after the day they were switched off. |

## Run it on your computer

Needs Python 3.12.

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt      # macOS/Linux: .venv/bin/pip
```

Create a `.env` file next to `manage.py`:

```
DEBUG=1
ALLOW_PASSWORD_LOGIN=1
SITE_NAME=Supreme Hub
```

```bash
.venv/Scripts/python manage.py migrate
.venv/Scripts/python manage.py seed_demo           # optional: made-up colleagues, teams, news, posts and events
.venv/Scripts/python manage.py runserver
```

Open http://localhost:8000. Demo accounts use first names as usernames: `amelia` is the admin, `sophie` can publish news, `hannah` and `liam` are new starters with a journey. The shared demo password is `DEMO_PASSWORD` in `hub/management/commands/seed_demo.py`.

To try push notifications locally, add the two lines from `python manage.py vapid_keys` to `.env` and run `python manage.py tick` (or `scheduler`) in a second terminal. Browsers allow push on `localhost` and on HTTPS sites only.

Run the tests (156 tests across all apps):

```bash
.venv/Scripts/python manage.py test
```

> Windows note: if the project sits in a very deep folder, Python can fail to import some Django files (the 260-character path limit). Keep the project in a short path such as `C:\code\staff-hub`, or turn on Windows long paths.

## Demo server on Fly.io

A public demo with made-up data, for showing the hub to someone outside your computer. Not for real staff data: one machine, SQLite, no email. Settings are in `fly.toml`.

```bash
fly apps create staffhub-demo-q7k4
fly volumes create hub_data --region lhr --size 1 -y
fly secrets set SECRET_KEY=<a long random string>      # optional: also the two lines from manage.py vapid_keys, for push
fly deploy --ha=false
fly ssh console -C "setpriv --reuid=app --regid=app --init-groups python manage.py seed_demo --force"
fly ssh console -C "setpriv --reuid=app --regid=app --init-groups python manage.py demo_logins Amy Chambers --force"
# Later, after the demo pictures change: swap them in place, keeping sign-ins, posts and comments.
fly ssh console -C "setpriv --reuid=app --regid=app --init-groups python manage.py seed_demo --refresh-pictures --force"
```

`demo_logins` prints two sign-ins, `amy.admin` (sees and manages everything) and `amy.staff` (a normal colleague), with a new password. Run it again to reset the password, or with another name for another visitor. On the demo server the seeded colleagues have no password, so the shared one in `seed_demo.py` doesn't work there. Commands run as the `app` user so the database files stay writable by the server.

## Put it on Supreme's servers

What Supreme's IT needs to provide:

1. **A Linux server or VM with Docker** and Docker Compose 2.17 or newer (2 CPUs, 4 GB RAM and 100 GB disk is plenty for 500 people; video uploads drive disk use).
2. **An address and HTTPS**, for example `hub.supreme.co.uk`, through their existing load balancer or reverse proxy, forwarding to the server's port 8080. The proxy must pass on the original `Host` header (not swap in the server's address), add `X-Forwarded-For` with the visitor's address, and set `X-Forwarded-Proto: https`. Without the first, every page is refused; without the second, all staff share one request limit.
3. **An Entra ID app registration**: single tenant, redirect URI `https://hub.supreme.co.uk/oidc/callback/`, plus a client secret, and the Microsoft Graph application permission `User.Read.All` with admin consent (for the leaver check). (Google Workspace works too, without the leaver check; see `.env.example`.)
4. **An SMTP relay** for the daily digest and disk alerts.
5. **Their proxy's address** for `TRUSTED_PROXY` in `.env`. nginx believes only that proxy about who the visitor is (for request limits and the security log). Also a firewall rule so only the proxy can reach the server's port 8080, and an upload limit of at least 260 MB on their proxy.
6. **Outbound HTTPS** from the server to the push services (`fcm.googleapis.com`, `*.push.apple.com`, `*.push.services.mozilla.com`, `*.notify.windows.com`) if push is wanted.
7. Optional: a **LibreTranslate** server inside their network for "See translation".

Then on the server:

```bash
cp .env.example .env          # fill in every value marked required, plus SSO and email
docker compose run --rm app python manage.py vapid_keys      # paste the two lines into .env for push
docker compose up -d --build
docker compose exec app python manage.py createsuperuser   # first admin (break-glass account)
```

The first admin's password only works while `ALLOW_PASSWORD_LOGIN=1`. Normally leave it at `0` so everyone, admins included, signs in with their work account. To make someone an admin later, have them sign in once with SSO, then tick "staff status" (and permissions) on their user in the admin.

**Roles** (in the admin, under Authentication, Groups; then add people and tick their "staff status" if they need the admin):

- **Moderators:** view, change and delete for posts, comments and reports, and view for log entries. The change permission for posts also lets them pin posts and see photos of hidden and deleted posts.
- **Communications:** "Can publish news". Add "Can view usage figures" for the Insights page.
- **Organisation admins:** change for groups and units, to build the organisation (Head Office, departments, locations, teams) and place people in it.
- **Editors:** add, change and delete for documents, folders, featured links, articles and categories (files and knowledge base), journeys, and vacancies.

**House rules:** agree the wording in `hub/templates/hub/house_rules.html` with Supreme (HR and data protection), set `PRIVACY_NOTICE_URL`, and bump `POLICY_VERSION` whenever the rules change.

**What's new:** add an entry under "Feature notes" in the admin after each update; staff see a count next to About and help until they've opened it.

**Updates:** `git pull && docker compose up -d --build`. Database changes apply automatically on start.

**Backups** (schedule daily, keep copies off the server):

```bash
docker compose exec -T db pg_dump -U hub hub | gzip > hub-$(date +%F).sql.gz
docker run --rm -v staff-hub_media:/data -v "$PWD":/backup alpine tar czf /backup/media-$(date +%F).tgz -C /data media
```

(The volume name starts with the folder name the project sits in; check with `docker volume ls`.)

## Security notes

- Every page requires sign-in (Django's `LoginRequiredMiddleware`); only the sign-in page, the SSO callback, the home-screen icon/manifest and the push service worker are public.
- A Content Security Policy only allows scripts from the hub itself and forbids framing; the browser also gets no access to camera, microphone or location.
- Uploaded files are served by nginx only after the app has checked the session and that the person may see them (`X-Accel-Redirect`); the files folder is not public.
- Uploads are checked by their content, not the file name. Photos are re-encoded and videos are re-packaged without metadata; anything ffmpeg or the image library can't read is rejected.
- Typed text is escaped before any formatting is added; links must start with `http://` or `https://`.
- Push subscriptions are only accepted for the known push services, so the server can't be made to send requests elsewhere. Push messages are encrypted end to end; people can hide the text from their lock screen.
- Translation sends the post's text to `TRANSLATE_URL` only, so point it at a server inside Supreme's network.
- Security events go to the `hub.security` log as JSON lines (`docker compose logs app scheduler`); point Supreme's SIEM at them.

## Before go-live: Supreme's side

The code can't do these; they decide how safe the hub really is.

- **Require multi-factor sign-in** for this app in Entra ID Conditional Access (optionally, company-managed devices only). The single biggest protection.
- **HTTPS end to end**, then set `SECURE_SSL_REDIRECT=1` and `SECURE_HSTS_SECONDS=31536000`. Firewall the server so only the proxy reaches it; limit `/admin/` to the office network or VPN at the proxy.
- **Encrypted disks and encrypted off-site backups**, with a test restore every quarter.
- **Monthly patching** of the server, Docker images (`docker compose pull && docker compose up -d --build --pull always`, which also updates Postgres and nginx) and Python libraries (`pip-audit -r requirements.txt` flags known holes).
- **A certificate instead of a client secret** for the Entra app, and `.env` readable only by the account that runs Docker (`chmod 600 .env`).
- **Paperwork:** a data protection impact assessment (DPIA), a staff privacy notice, retention periods (`POST_RETENTION_DAYS`, `LEAVER_RETENTION_DAYS`, `CHAT_RETENTION_DAYS`), named moderators and an HR escalation route, a breach plan (serious breaches go to the ICO within 72 hours), and an independent penetration test before rollout.
- Run `python manage.py check --deploy` against the production settings.

## Known shortcuts (upgrade when needed)

- Videos are cleaned but not converted between formats, so an iPhone HEVC video may not play in every browser. Add background transcoding if staff report problems.
- One photo description applies to every photo in a post.
- Chat checks for new messages every few seconds instead of keeping a live connection; fine for 500 people.
- Speed was measured with a year of made-up use by 500 staff: `docs/operations/CAPACITY.md` has the numbers, the server settings and how to measure again (`seed_load`, then `benchmark`, on a test copy only).
- Two colleagues with exactly the same name are both mentioned by "@Name".
- Calendar files don't fold long lines (all major calendar apps accept them).
- Job titles and departments are typed by staff; only names, emails and account status come from Entra ID. Organisation units are set up by hand in the hub.
- The house rules text is a starting point, not legal advice; Supreme's HR and data protection lead should approve it.

## Plan

Done: everything in "What's in version 2", tests (143), Docker setup.

Next, in order:

1. **Demo to Supreme** with seeded data and their branding.
2. **Connect Supreme's Entra ID** in a test environment and sign in with real accounts.
3. **Pilot with one department** for a few weeks; fix what they hit.
4. **Independent security test**, then full rollout.

Later, if the pilot asks for them: video conversion, syncing job titles and departments from Entra ID, "kudos" or recognition posts, native app-store apps.

Monitoring bots: any bot that reads logs or posts sends employee data to its AI provider, so it needs Supreme's approval as a sub-processor first. Uptime checks and restarts need no access to content.
