# Changelog

Every release of One Supreme, newest first. Versions are `MAJOR.MINOR.PATCH`, and each one is a git tag such as
`v2.0.0` and an image such as `ghcr.io/<organisation>/one-supreme:2.0.0`. `docs/operations/RELEASES.md` says what
each number means, and how to cut, install and roll back a release.

Each entry says whether it changes the database and whether it needs new settings, because that decides how it is
rolled back:

- **Database changes: none** or **adds only**: roll back by running the previous image.
- **Database changes: removes or rewrites**: rolling back also means restoring the backup taken before installing.

## [2.0.0] - 2026-12-01

The first release on Supreme's own servers.

**Database changes:** creates the whole database on first start. There is no earlier version to roll back to: the
Fly.io demo holds made-up data only and is never copied across.

**New settings:** all of them, as a new install (`.env.example`).

### Added

- Single sign-on with Microsoft Entra ID, limited to Supreme's email domains. Leavers are signed out within
  15 minutes and switched off by a nightly check.
- Feed with formatting, photos and videos, polls, reactions, comments with replies, @mentions, pinned posts,
  announcements and scheduled posts.
- News with covers, audiences, drafts, scheduling and "confirm you've read this".
- Chat, one-to-one and in groups, with pictures, unread counts, mute and report.
- Public and private groups, the organisation (units, departments, locations, teams), events with RSVPs and
  reminders, the people directory, files and knowledge base, onboarding journeys and internal jobs.
- Alerts in the hub, by push and in a daily email digest, with quiet hours and Do not disturb.
- One search across everything a person may see.
- Moderation in the admin, with reports, hiding and restoring, and a read-only audit log.
- House rules on first sign-in, "download my data", and automatic clean-up of old content.
- Security log as JSON lines, per-person limits, request limits in nginx, and metadata stripped from uploads.
- Docker Compose setup for one server: Postgres 17, the app, the scheduler and nginx.
- Release pipeline: every test also runs on Postgres 17, and each version tag builds, checks and publishes the
  server's image to GitHub's container registry with a record of how it was built.
