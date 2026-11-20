# Releases

How a change becomes a version on Supreme's server, how IT installs it and how to go back. The hub's maintainers
cut releases on GitHub. Supreme IT installs them on the server, as `onesupreme` in `/opt/one-supreme` (RUNBOOK.md).
`CHANGELOG.md` lists every release.

## Version numbers

Each release is a git tag `vMAJOR.MINOR.PATCH`, such as `v2.1.0`. Its image is
`ghcr.io/<organisation>/one-supreme:2.1.0`. The number says how much care the install needs:

| Release | What it may contain | Rolling back |
|---|---|---|
| Patch, `2.0.1` | Fixes, security fixes, library and base image updates. No database changes, no new settings. | Run the previous image. |
| Minor, `2.1.0` | New features and new optional settings. Database changes that only add (tables, columns, indexes). | Run the previous image. |
| Major, `3.0.0` | Anything IT must act on: a required new setting, database changes that remove or rewrite, a new Postgres version. | Run the previous image and restore the backup. |

The version is in two places, and the release refuses a tag that doesn't match both: `APP_VERSION` in
`config/settings.py` (staff see it on the About page) and a `## [2.1.0]` entry in `CHANGELOG.md`.

**How often:** small releases, often. A patch whenever fixes are merged (a security fix within 48 hours if the hole
is being exploited, as in RUNBOOK.md), a minor release about once a month.

## Set up once

On GitHub (organisation owner, after GITHUB-SETUP.md):

1. **Protect the version tags.** **Settings**, **Rules**, **Rulesets**, **New ruleset**, **New tag ruleset**.
   Name: `Version tags`. **Enforcement status**: **Active**. **Bypass list**: **Add bypass**, **Repository admin**.
   **Target tags**: **Add target**, **Include by pattern**, `v*`. Tick **Restrict creations**, **Restrict updates**
   and **Restrict deletions**, then **Create**. Only admins can now create a version tag, and nobody can move one by
   accident.
2. **Require the Postgres tests.** Once `.github/workflows/postgres.yml` has run once, add `Tests on Postgres 17` to
   the required checks of the `Protect main` ruleset (GITHUB-SETUP.md, step 6).
3. **After the first release**, open the organisation's **Packages** tab, then `one-supreme`. Check that it is
   **Private** and is linked to the `one-supreme` repository.

On the server (Supreme IT):

1. The server must reach `ghcr.io` and `pkg-containers.githubusercontent.com` on port 443, through the proxy if
   there is one.
2. On GitHub, sign in as the account the organisation uses for the server, and make a **personal access token
   (classic)** with only **read:packages**, valid for a year. Put its renewal in IT's calendar.
3. Sign the server in once. Docker asks for the token as the password and keeps it in `~/.docker/config.json`:
   ```bash
   docker login ghcr.io -u <that account>
   ```

## Cut a release (maintainers)

1. **Pick the number** from what was merged since the last release (`git log --oneline v2.0.0..main`) and the table
   above.
2. **On a branch:** set `APP_VERSION` in `config/settings.py`, and add the entry at the top of `CHANGELOG.md`:
   `## [2.1.0] - <the day you tag>`, what changed, **Database changes:** (none, adds only, or removes or rewrites)
   and **New settings:**. Check every new migration (`git diff --stat v2.0.0 -- '*/migrations/*'`) against
   [Safe database changes](#safe-database-changes), and write what its SQL does in the pull request.
3. **Pull request**, green checks, merge.
4. **Tag the merged commit:**
   ```bash
   git switch main
   git pull
   git tag -a v2.1.0 -m "One Supreme 2.1.0"
   git push origin v2.1.0
   ```
5. **Watch** the **Release** run on the **Actions** tab. It runs every test on Postgres 17, then checks that the tag
   is on `main` and matches `APP_VERSION` and the changelog. It builds the image, applies every database change to
   an empty Postgres 17, checks no migration is missing, starts the image and checks it answers. It refuses a
   version that is already published, then publishes the image with a record of how it was built (the commit, the
   Dockerfile, the base image).
6. **Send IT** the version, the changelog entry and the `HUB_IMAGE=` line from the run's summary page.

If the run fails, nothing is published. If the fault is outside the code (GitHub down, a test that failed once),
**Re-run failed jobs**. Otherwise fix it through a pull request and release the next patch number. Never reuse or
move a version tag.

## Install a release (Supreme IT)

A new server follows INSTALL.md instead, with the release's `HUB_IMAGE=` line in `.env` and
`docker compose up -d --no-build` in place of `--build`.

For an update, pick a weekday when someone can watch the hub for an hour afterwards. Not between 02:00 and 03:00 UTC: the nightly
backup is reading every table then, and a database change would wait for it while every page waits for the change.

1. **Read the release's entry** in `CHANGELOG.md`: database changes, new settings, anything to do by hand.
2. **Back up** (BACKUPS.md, "Back up now") and wait for it to finish.
3. **Note what runs now**, for a rollback. Write both in IT's change log:
   ```bash
   git describe --tags
   grep '^HUB_IMAGE=' .env
   ```
4. **Get the release's files** and look for new settings:
   ```bash
   git fetch --tags
   git diff v2.0.0 v2.1.0 -- .env.example docker-compose.yml   # the version running now, then the new one
   git checkout v2.1.0
   ```
   Add any new settings to `.env`.
5. **Point `.env` at the new image:** replace the `HUB_IMAGE=` line with the one IT was sent. It ends in
   `@sha256:...`, which pins the server to exactly the image the release built.
6. **Download it and see which database changes it will make.** Nothing changes yet:
   ```bash
   docker compose pull app scheduler
   docker compose run --rm --no-deps app python manage.py migrate --plan
   ```
   "No planned migration operations" means no database changes.
7. **Install it:**
   ```bash
   docker compose up -d --no-build
   docker compose logs -f app
   ```
   Database changes apply as it starts ("Applying ..." lines). It's ready at gunicorn's "Listening at". Press
   Ctrl+C to stop watching. `--no-build` matters: the server runs only images the release built, never its own.
8. **Check:** `docker compose ps` shows everything "Up". Sign in, open a post, the people directory and the admin;
   the About page shows the new version.

## Roll back

If the new release misbehaves, decide within the hour. The release's changelog entry says which way back.

**Database changes: none or adds only.** Takes a few minutes, and nothing is lost. The previous version doesn't use
the added tables and columns, so they can stay.

```bash
git checkout v2.0.0          # the version noted in step 3
# in .env, put back the HUB_IMAGE= line noted in step 3
docker compose pull app scheduler
docker compose up -d --no-build
```

**Database changes: removes or rewrites**, or the previous version shows errors:

1. Stop the hub: `docker compose stop web app scheduler`.
2. Restore the backup from step 2 (BACKUPS.md, "Restore on the same server").
3. Run the four commands above.

Posts and messages written since that backup are lost, which is why the decision can't wait. Never run database
changes backwards (`migrate <app> <number>`) on the live hub: it can delete data, and the restore is the way back
that IT has tested.

## Safe database changes

For the maintainers. On the server the hub uses Postgres 17; on a computer and in `ci.yml` it uses SQLite, which
behaves differently. `.github/workflows/postgres.yml` runs every test on Postgres too, but tests start from an empty
database, so they can't show what a change does to a hub full of posts. These rules do.

### Expand, then contract

A release only adds to the database. Then the previous version still runs on it, and a rollback needs no restore.

- **Adding** a table, a column or an index is fine. A new column needs `null=True` or a database default
  (`db_default=`). A plain `default=` isn't enough: Django fills the existing rows with it, then removes it from the
  database, so the previous version's inserts fail on the new column.
- **Removing** a column or table comes at least one release after the code stopped using it. That release must have
  run for two weeks, so nobody needs to roll back past it. The release that removes it is a major release, marked
  "Database changes: removes or rewrites".
- **Renaming** is adding the new one, copying the data across, switching the code, and removing the old one in a
  later release. Never `RenameField` or `RenameModel` on a table that holds data.
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
Postgres's, not SQLite's (SQLite rebuilds whole tables, which says nothing about Postgres):

```bash
# On the server, after step 6 of the install: the new image, against the live database. Changes nothing.
docker compose run --rm --no-deps app python manage.py sqlmigrate hub 0007

# On a computer with a Postgres 17 running locally, after python manage.py migrate:
DB_HOST=localhost python manage.py sqlmigrate hub 0007
```

Look for the slow steps above (`CREATE INDEX`, `ALTER COLUMN ... TYPE`, `SET NOT NULL`, `ADD CONSTRAINT`), and for
`DROP COLUMN` or `DROP TABLE`: is the previous version still using it? Add `--backwards` to see the reverse.

## Review of the existing migrations (20 November 2026)

All 11 migrations were read and their Postgres SQL produced with Django 5.2.19. **They are safe for 2.0.0:** they
run once, on an empty database, at the first install, so no lock lasts more than a moment and there is nothing to
roll back to. On a hub full of data they would not be, so here is what to avoid next time:

| Migration | What it does on Postgres | What it would mean on a hub with data |
|---|---|---|
| `chat`, `hub`, `jobs`, `journeys`, `library` 0001 | Creates the tables, indexes and foreign keys. | Nothing: new tables. |
| `hub` 0002 | Adds deleted-at and deleted-by columns to posts and comments, and `policy_version` to people. | `policy_version` is added `NOT NULL DEFAULT ''`, then the default is dropped, so the previous version couldn't create accounts. The two new foreign keys are checked at once, reading every post and comment. |
| `hub` 0003 | Adds `deactivated_at` and a unique `sso_id` to people, an index on attachment files, and dates existing leavers. | The indexes block writes to people and attachments while they build (with a second `_like` index each). The data step shares a transaction with the table changes. |
| `hub` 0004 | 13 new tables; 43 new columns on posts, people, groups, alerts, comments, reports and RSVPs; 9 indexes on those tables; the report CHECK constraint dropped and added again; then a data step that updates every post. | The riskiest. One transaction locks 7 of the busiest tables until the data step has rewritten every post, so the hub would stop for as long as that takes. 25 of the new columns are NOT NULL with the default dropped. Adding the CHECK again reads every report. Next time: one migration that adds, one that changes data, one for the indexes. |
| `hub` 0005 | Changes the permission list only. | Nothing: no SQL. |
| `hub` 0006 | Drops `last_digest_at` from people. | A removal in the same release that added the column (0004). Fine before go-live; after it, the removal must wait a release. |
| `library` 0002 | Drops `content_type` from documents. | As 0006. |

The Postgres tests apply all 11 migrations on every push. The release applies them once more, from the image itself,
before it publishes.
