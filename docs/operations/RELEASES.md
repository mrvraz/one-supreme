# Releases

How a change becomes a version on Supreme's server, how IT installs it and how to go back. The hub's maintainers
cut releases on GitHub. Supreme IT installs them on the server, as `onesupreme` in `/opt/one-supreme` (RUNBOOK.md).
`CHANGELOG.md` lists every release.

This page is the one release procedure. Where another guide mentions releases, upgrades or rollbacks, it points
here.

## Version numbers

Each release is a git tag `vMAJOR.MINOR.PATCH`, such as `v2.1.0`. Its image is
`ghcr.io/<organisation>/one-supreme:2.1.0`, whatever the repository is called.

| Release | What it may contain |
|---|---|
| Patch, `2.0.1` | Fixes, security fixes, library and base image updates. No database changes, no new settings. |
| Minor, `2.1.0` | New features and new optional settings. Database changes that add: tables, columns, indexes, links to existing tables. |
| Major, `3.0.0` | Anything IT must act on: a required new setting, database changes that remove or rewrite, a new Postgres version (which always needs the backup to roll back). |

How a release is rolled back depends on the **Database changes:** line of its changelog entry, not on its number:

- **none** or **adds only**: run the previous image. "Adds only" means the previous version, which ignores the
  additions, still shows and protects correctly every row the new version wrote.
- **needs the backup to roll back**: run the previous image and restore the backup taken before installing. This
  covers every removal or rewrite, and also additions that the previous version would trip over or would show
  wrongly ([Expand, then contract](#expand-then-contract)). A minor release can have them:
  - a new link from any table to an existing one, such as people or posts, and a new rule on an existing table;
  - a new column or table that hides something or limits who sees it: a private flag, an audience, a draft, a soft
    delete, a moderation hide, a privacy setting, a block. The previous version ignores it and shows everyone what
    it hid;
  - a release that moves data to a new column or table and stops writing the old one. The previous version reads
    the old one, which no longer has the latest edits.

A release that changes the Postgres version always needs the backup to roll back, whatever its **Database changes:**
line says, and its entry says how: the previous Postgres can't open the new version's data.

The version is in two places, and the release refuses a tag that doesn't match both: `APP_VERSION` in
`config/settings.py` (staff see it on the About page) and a `## [2.1.0]` entry in `CHANGELOG.md`.

**How often:** small releases, often. A patch whenever fixes are merged (a security fix within 48 hours if the hole
is being exploited, as in RUNBOOK.md), a minor release about once a month. And at least one release every month,
before IT's patching on the second Wednesday: if nothing else has merged, a patch with only the version and the
changelog entry "Base image and Debian updates". The server never builds the hub, and each release is built from
scratch on GitHub, so only a release brings the newest base image and Debian packages (OpenSSL, ffmpeg) into the
hub. For the same reason, an urgent fix in a Debian package or in Python means a patch release the same day.

## Set up once

### On GitHub (organisation owner, after GITHUB-SETUP.md)

1. **Protect the version tags and names.** **Settings**, **Rules**, **Rulesets**, **New ruleset**, **New tag
   ruleset**. Name: `Version tags`. **Enforcement status**: **Active**. **Bypass list**: **Add bypass**,
   **Repository admin**. **Target tags**: **Add target**, **Include by pattern**, `v*`. Tick **Restrict creations**,
   **Restrict updates** and **Restrict deletions**, then **Create**. Only admins can now create a version tag, and
   nobody can move one by accident. If a tag ruleset with these settings already exists (such as
   `Protect releases`), skip this tag ruleset.
   Then, so nobody can push a branch with a version's name, whose run would look like the release's: **New
   ruleset**, **New branch ruleset**. Name: `Version names`. **Enforcement status**: **Active**. **Bypass list**:
   **Add bypass**, **Repository admin**, nothing else. **Target branches**: **Add target**, **Include by pattern**,
   `v*`. Tick only **Restrict creations**, then **Create**. Branch names that start with `v` are now for admins
   only, so start other branches' names with another letter (`fix-video`, not `video-fix`).
2. **Require the Postgres tests.** Once `.github/workflows/postgres.yml` has run once, add `Tests on Postgres 17` to
   the required checks of the `Protect main` ruleset (GITHUB-SETUP.md, step 6).
3. **After the first release**, open the organisation's **Packages** tab, then `one-supreme`. Check that it is
   **Private** and is linked to this repository (`staff-hub` after GITHUB-SETUP.md).

### The server's GitHub account (Supreme IT, with an organisation owner)

The server downloads images from `ghcr.io`, which accepts only a GitHub account's token, not the server's deploy
key. So the server gets an account of its own. It belongs to no member of staff, so nothing breaks when someone
leaves.

1. **Create the account** in a private browser window, at https://github.com/signup. Email: an address of IT's
   shared mailbox, so GitHub's warnings (such as a token about to expire) reach IT. Username: for example
   `supreme-hub-server`. A generated password. Turn on two-factor authentication with an authenticator app: the
   organisation requires it. Keep the password, the two-factor secret and the recovery codes in IT's password
   vault, as "One Supreme server GitHub account".
2. **An organisation owner invites it**: the organisation's **People**, **Invite member**, the account's username,
   role **Member**, never **Owner**. Accept the invitation while signed in as the account. It takes one seat of
   the Team plan. The organisation's base permission is **Read** (GITHUB-SETUP.md, step 1), so it can read the
   repository and download its images, and change nothing. Don't add it to a team or give it any other role.
3. **Make its token**, signed in as the account: profile picture, **Settings**, **Developer settings**,
   **Personal access tokens**, **Tokens (classic)**, **Generate new token (classic)**. Note: `one-supreme server`.
   Expiration: **Custom**, a year from today. Tick only **read:packages**. Click **Generate token** and put the
   token in the same vault entry (GitHub shows it once). GitHub's container registry needs a classic token.
4. **Renewing it** is Supreme IT's job, every year. Put a reminder in IT's calendar two weeks before the expiry
   date; GitHub also emails the account a week before. Sign in as the account, open the token, click
   **Regenerate token**, pick the same expiry, then sign the server in again (step 3 below) and update the vault.
   If it expires anyway, the hub keeps running, but `docker compose pull` fails with "denied" or "unauthorized",
   and so does a rollback, because it downloads the previous image again. Renew it first, then carry on.

### On the server (Supreme IT)

1. **Docker Compose 2.24 or newer:** `docker compose version`. `docker-compose.release.yml` needs it.
2. **The firewall** lets the server reach `ghcr.io` and `pkg-containers.githubusercontent.com` on port 443, through
   the proxy if there is one.
3. **Sign the server in**, as `onesupreme`. Docker asks for the token from the vault as the password and keeps it in
   `~/.docker/config.json`, which only `onesupreme` can read:
   ```bash
   docker login ghcr.io -u supreme-hub-server   # the server's account
   ```
4. **Turn on the release file.** At the end of `.env`, remove the `#` from the `COMPOSE_FILE=` and `HUB_IMAGE=`
   lines (copy them from `.env.example` if `.env` is older). `HUB_IMAGE=` gets the release's line, as in steps 4
   and 5 of [Install a release](#install-a-release-supreme-it). From then on the hub runs only images the release
   built, and `docker compose build` or `--build` builds only the services that have no published image (the
   backup tools).

A **new server** follows INSTALL.md, with the release's tag in its step 2. Between its steps 4 and 5, do the four
steps above, after checking the tag and copying its `HUB_IMAGE=` line as in steps 4 and 5 below. INSTALL.md's
`docker compose build` then builds only the backup tools, and its next command downloads the hub's image.

## Cut a release (maintainers)

1. **Pick the number** from what was merged since the last release (`git log --oneline v2.0.0..main`) and the table
   above.
2. **On a branch:** set `APP_VERSION` in `config/settings.py`, and add the entry at the top of `CHANGELOG.md`:
   `## [2.1.0] - <the day you tag>`, what changed, **Database changes:** (none, adds only, or needs the backup to
   roll back, with the reason) and **New settings:**. Check every new migration
   (`git diff --stat v2.0.0 -- '*/migrations/*'`) against [Safe database changes](#safe-database-changes), and
   write what its SQL does in the pull request.
3. **Pull request**, green checks, merge.
4. **Tag the merged commit** (only admins can):
   ```bash
   git switch main
   git pull
   git tag -a v2.1.0 -m "One Supreme 2.1.0"
   git push origin v2.1.0
   ```
5. **Watch** the **Release** run on the **Actions** tab. It runs every test on Postgres 17, then checks that the tag
   is on `main` and matches `APP_VERSION` and the changelog. It builds the image, applies every database change to
   an empty Postgres 17, checks no migration is missing, starts the image and checks its sign-in page answers. It
   refuses a version that is already published, then publishes the image with a record of how it was built (the
   commit, the Dockerfile, the base image).
6. **Tell IT** the version and its changelog entry. Don't send the `HUB_IMAGE=` line: IT copies it from the run
   itself.

If the run fails, nothing is published. If the fault is outside the code (GitHub down, a test that failed once),
**Re-run failed jobs**. Otherwise fix it through a pull request and release the next patch number. Never reuse or
move a version tag.

## Install a release (Supreme IT)

For an update, pick a weekday when someone can watch the hub for an hour afterwards. Not between 02:00 and 03:00
UTC: the nightly backup is reading every table then, and a database change would wait for it while every page waits
for the change.

1. **Read the release's entry** in `CHANGELOG.md`: database changes, new settings, anything to do by hand.
2. **Back up** (BACKUPS.md, "Back up now") and wait for it to finish.
3. **Note what runs now**, for a rollback. Write both in IT's change log:
   ```bash
   git describe --tags
   grep '^HUB_IMAGE=' .env
   ```
4. **Check the release is on `main`**, then get its files and look for new settings:
   ```bash
   git fetch origin main --tags
   git merge-base --is-ancestor v2.1.0 origin/main && echo "On main"
   ```
   It must print `On main`. If it prints nothing, stop and tell the maintainers: only `main` is reviewed.
   ```bash
   git diff v2.0.0 v2.1.0 -- .env.example docker-compose.yml docker-compose.release.yml   # now, then new
   git checkout v2.1.0
   ```
   Add any new settings to `.env`.
5. **Copy the `HUB_IMAGE=` line from the release's own run**, never from an email or a message. Any workflow in
   the repository can push an image under any version number, so only the line from that run is trusted. Sign in
   to GitHub with your own account or the server's account. In the repository: **Actions**, then **Release** in the
   left menu, then the run marked `v2.1.0`. Check that it was started by a push of `v2.1.0`, that it has a green
   tick, and that **Workflow file** in its left menu shows `.github/workflows/release.yml`.
   Then check that it ran the tagged commit. On the server, this prints the tag's commit id, 40 characters:
   ```bash
   git rev-parse "refs/tags/v2.1.0^{commit}"
   ```
   On the run's page, click the short commit id next to "Triggered via push". The commit's page opens, and its
   address ends with the run's full commit id. Compare all 40 characters: the 7-character short id is not enough,
   because a made-up commit can be given the same short id in minutes. If they differ, or if more than one Release
   run is marked `v2.1.0`, stop and tell the maintainers: someone ran a workflow of their own under the version's
   name. A run of the tagged commit can only come from `main`'s reviewed `release.yml`.
   On the run's **Summary**, under "Published", is the line. Put it in `.env` in place of the old `HUB_IMAGE=`
   line. It starts with `ghcr.io/<organisation>/one-supreme:2.1.0@sha256:`, and the digest after `@sha256:` pins
   the server to exactly the image that run built and checked.
6. **Download it and see which database changes it will make.** Nothing changes yet:
   ```bash
   docker compose pull app scheduler
   docker compose run --rm --no-deps app python manage.py migrate --plan
   ```
   "No planned migration operations" means no database changes.
7. **Install it:**
   ```bash
   docker compose up -d --build
   docker compose logs -f app
   ```
   `--build` rebuilds the backup tools from the release's files; the hub itself is never built on the server.
   Database changes apply as it starts ("Applying ..." lines). It's ready at gunicorn's "Listening at". Press
   Ctrl+C to stop watching.
8. **Check:** `docker compose ps` shows everything "Up". Sign in, open a post, the people directory and the admin;
   the About page shows the new version.

## Roll back

If the new release misbehaves, decide within the hour. The **Database changes:** line of the release's changelog
entry says which way back.

**Database changes: none or adds only.** Takes a few minutes, and nothing is lost. The previous version doesn't use
the added tables and columns, so they can stay. This never covers additions that hide something or limit who sees
it, or data moved to a new place: the previous version would show everyone what they hid, or miss the latest
edits, so those releases say "needs the backup to roll back" ([Version numbers](#version-numbers)). Nor a release
that changes the Postgres version, whatever its line says: it always needs the backup, and its entry says how.

```bash
git checkout v2.0.0          # the version noted in step 3
# in .env, put back the HUB_IMAGE= line noted in step 3
docker compose pull app scheduler
docker compose up -d --build
```

`--build` rebuilds the backup tools from the previous version's files.

**Database changes: needs the backup to roll back**, or the previous version shows errors. Keep to this order. The
hub must not start while `.env` and the files still name the new release: it would make the new release's database
changes again, on the database you have just restored.

1. **Put the previous version back**, with the first three commands above: `git checkout` of the version noted in
   step 3, its `HUB_IMAGE=` line in `.env`, and `docker compose pull app scheduler`. The hub keeps running until
   the next step.
2. **Stop the hub:** `docker compose stop web app scheduler backup`.
3. **Restore the backup from install step 2:** BACKUPS.md, "Restore on the same server", steps 1 to 3 only (pick
   the set, stop the hub, restore). Don't do its step 4 (`docker compose up -d`): the next step starts the hub
   instead, and also rebuilds the backup tools for the previous version.
4. **Start the hub:** `docker compose up -d --build`, then check it as in install step 8. Then do BACKUPS.md's
   steps 5 to 7: check, redo deletions made since the backup, clean up.

Posts and messages written since that backup are lost, which is why the decision can't wait. Never run database
changes backwards (`migrate <app> <number>`) on the live hub: it can delete data, and the restore is the way back
that IT has tested.

## Safe database changes

For the maintainers. On the server the hub uses Postgres 17; on a computer and in `ci.yml` it uses SQLite, which
behaves differently. `.github/workflows/postgres.yml` runs every test on Postgres too, but tests start from an empty
database, so they can't show what a change does to a hub full of posts. These rules do.

### Expand, then contract

A release should only add to the database. Then the previous version still runs on it, and, unless the additions
hide something (below), a rollback needs no restore.

- **Adding** a table, a column or an index is fine. A new column needs `null=True` or a database default
  (`db_default=`). A plain `default=` isn't enough: Django fills the existing rows with it, then removes it from the
  database, so the previous version's inserts fail on the new column.
- **Links and rules on existing tables** only add, but they need the backup to roll back: a new `ForeignKey`,
  `OneToOneField` or `ManyToManyField` that points at an existing table (people, posts, groups), from a new table
  or an old one, and a new unique or CHECK constraint on columns the previous version writes. The previous
  version doesn't know about them. When it deletes a person or a post that a new row points at, Postgres refuses at
  the end of the transaction, so the nightly clean-up, leavers and erasure in the admin fail until the restore. Its
  writes that break a new rule fail too. Mark such a release "needs the backup to roll back". A link from an
  existing table to a new one is fine: the previous version never deletes from the new table.
- **Anything that hides something or limits who sees it** only adds, but it needs the backup to roll back: a new
  column or table for a private flag, an audience, a draft, a soft delete, a moderation hide, a privacy setting or
  a block. The previous version ignores it, so after a rollback it would show what the new version hid to all
  staff, in the feed, search, digests and push. Mark such a release "needs the backup to roll back".
- **Removing** a column or table comes at least one release after the code stopped using it. That release must have
  run for two weeks, so nobody needs to roll back past it. The release that removes it is a major release, marked
  "needs the backup to roll back".
- **Renaming**, and any change that moves data to a new column or table, is adding the new place, copying the data
  across, switching the code to read the new place, and removing the old one in a later release. Until that
  release, the code keeps writing both the old and the new place, so the previous version still finds every edit.
  A release that stops writing the old place sooner needs the backup to roll back: the previous version would read
  the old place, so edits would be lost and posts written since would show an empty body. Never `RenameField` or
  `RenameModel` on a table that holds data.
- **Changing data** (`RunPython`) goes in a migration of its own, never in the same one as a change to the tables,
  and gets a reverse step (`RunPython.noop` if nothing needs undoing). On Postgres both share one transaction, so
  table locks last as long as the data change, and Django warns it can fail with "pending trigger events".

### No long table locks

On Postgres each migration runs as one transaction and keeps its locks until it ends. Changing a table
(`ALTER TABLE`) blocks everyone reading or writing it. If it has to wait for a lock, every query on that table
queues behind it, and the hub hangs.

- **Quick** (a lock for a moment): adding a table; adding a column that is nullable or has a fixed default; making
  a text column longer; dropping a column, an index or a table.
- **Slow** (the table is locked while Postgres reads or rewrites every row): creating an index, which blocks writes
  (Django creates one for each `db_index=True`, `ForeignKey` and `unique`, and a second `_like` one for text
  columns); changing a column's type; making a column NOT NULL; adding a CHECK, foreign key or unique constraint to a
  table that has rows; a `RunPython` that updates every row.

With about 500 staff the biggest tables (alerts, read receipts, reactions) stay in the hundreds of thousands of rows,
so a slow step usually takes a second or two. Before a release with slow steps, look at the sizes on the server:

```bash
docker compose exec db psql -U hub -d hub -c "SELECT relname, n_live_tup FROM pg_stat_user_tables ORDER BY n_live_tup DESC LIMIT 10"
```

For a table over a million rows, build the index without blocking writes: `AddIndexConcurrently` (from
`django.contrib.postgres.operations`) in a migration of its own with `atomic = False`. It only works on Postgres, so
that migration must check `schema_editor.connection.vendor` and create a plain index on SQLite.

### Check a migration's SQL with sqlmigrate

`sqlmigrate` prints the SQL a migration would run, without running it. The SQL depends on the database, so look at
Postgres's, not SQLite's (SQLite rebuilds whole tables, which says nothing about Postgres). For some changes, such as
removing an index or a constraint, it reads the database to find names, so run it on a database that doesn't have
the change yet:

```bash
# On the server, after step 6 of the install and before step 7: the new image, against the live database.
# Changes nothing.
docker compose run --rm --no-deps app python manage.py sqlmigrate hub 0007

# On a computer with Postgres 17 running locally: bring the database to the migration before, then print it.
DB_HOST=localhost python manage.py migrate hub 0006
DB_HOST=localhost python manage.py sqlmigrate hub 0007
```

Look for the slow steps above (`CREATE INDEX`, `ALTER COLUMN ... TYPE`, `SET NOT NULL`, `ADD CONSTRAINT`), for
`REFERENCES` to an existing table (a link: needs the backup to roll back), and for `DROP COLUMN` or `DROP TABLE`: is
the previous version still using it? Add `--backwards` to see the reverse.

## Review of the existing migrations (20 November 2026)

All 11 migrations were read and their Postgres SQL produced with Django 5.2.19. **They are safe for 2.0.0:** they
run once, on an empty database, at the first install, so no lock lasts more than a moment and there is nothing to
roll back to. On a hub full of data they would not be, so here is what to avoid next time:

| Migration | What it does on Postgres | What it would mean on a hub with data |
|---|---|---|
| `chat`, `hub`, `jobs`, `journeys`, `library` 0001 | Creates the tables, indexes and foreign keys. | Nothing: new tables. |
| `hub` 0002 | Adds deleted-at and deleted-by columns to posts and comments, and `policy_version` to people. | `policy_version` is added `NOT NULL DEFAULT ''`, then the default is dropped, so the previous version couldn't create accounts. The two new foreign keys point at people, so it couldn't delete anyone who had deleted a post or comment either: a rollback would need the backup. Both are checked at once, reading every post and comment. `deleted_at` hides deleted posts and comments, which the previous version would show again: another reason it would need the backup. |
| `hub` 0003 | Adds `deactivated_at` and a unique `sso_id` to people, an index on attachment files, and dates existing leavers. | The indexes block writes to people and attachments while they build (with a second `_like` index each). The data step shares a transaction with the table changes. The unique rule is on a new column the previous version never writes, so it doesn't stop a rollback. |
| `hub` 0004 | 13 new tables; 43 new columns on posts, people, groups, alerts, comments, reports and RSVPs; 9 indexes on those tables; the report CHECK constraint dropped and added again; then a data step that updates every post. | The riskiest. One transaction locks 7 of the busiest tables until the data step has rewritten every post, so the hub would stop for as long as that takes. 25 of the new columns are NOT NULL with the default dropped. Adding the CHECK again reads every report. Its new links point at people and posts, so a rollback past it would need the backup. So would its columns that hide things or limit who sees them: `Community.is_private`, `Post.is_draft`, `Post.audiences` and `User.share_email`. The previous version would show private groups' posts, drafts, news meant for some groups and hidden email addresses to all staff. Next time: one migration that adds, one that changes data, one for the indexes. |
| `hub` 0005 | Changes the permission list only. | Nothing: no SQL. |
| `hub` 0006 | Drops `last_digest_at` from people. | A removal in the same release that added the column (0004). Fine before go-live; after it, the removal must wait a release. |
| `library` 0002 | Drops `content_type` from documents. | As 0006. |

The Postgres tests apply all 11 migrations on every push. The release applies them once more, from the image itself,
before it publishes.
