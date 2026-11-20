# Capacity for 500 staff

How fast the hub stays after a year of use by about 500 staff, the server settings that go with it, and what to
watch at the 9am rush.

## Measure it yourself

Two commands do it. `seed_load` fills an empty database with a year of made-up use. `benchmark` opens the 15
busiest pages as an ordinary colleague and as a moderator, and prints a table of times, database queries and page
sizes.

Run them only on a database that exists to be measured and is thrown away afterwards. **Never on the live hub or
the test hub:** made-up people aren't in Entra ID, so the nightly leaver check there would refuse and email
`ADMIN_EMAILS` every night (INSTALL.md, The test hub). `seed_load` refuses any database that already has an account.

On your computer, with a scratch folder for the database (never your real one):

```bash
export DATA_DIR=/tmp/hub-load DEBUG=1
python manage.py migrate
python manage.py seed_load        # about a minute
python manage.py benchmark        # about three minutes; --sql also shows each page's slowest query
rm -r /tmp/hub-load               # when you're done
```

To measure on Postgres, use a spare machine or VM with Docker. Don't use the live or the test hub's server: the
measuring takes their memory and CPU. Make a fresh copy of the code and give it its own compose project
(`-p hub-load`). That gives it its own database and upload volumes, and only `db` and one-off `app` commands run,
so there is no scheduler, no digest and no leaver check:

```bash
cp .env.example .env
# In .env: made-up SECRET_KEY, DB_PASSWORD (and DB_APP_PASSWORD, if .env.example has it) and TRUSTED_PROXY=127.0.0.1.
# Leave the Entra ID (OIDC_...), email and push (VAPID_...) lines empty, and add
# EMAIL_BACKEND=django.core.mail.backends.dummy.EmailBackend so nothing can reach staff or Entra ID.
docker compose -p hub-load up -d db
docker compose -p hub-load run --rm app python manage.py migrate
docker compose -p hub-load run --rm app python manage.py seed_load --force
docker compose -p hub-load run --rm app python manage.py benchmark
docker compose -p hub-load down -v     # throws its database and uploads away
```

The benchmark opens pages the way a person would (opening a chat marks it read) and signs in directly as two
made-up accounts.

### What seed_load makes

All made up: names put together from short word lists, `example.com` addresses, and file names with no file behind
them. Nobody can sign in as these people, and none of them gets the daily email.

| What | How many | Shape |
|---|--:|---|
| Staff | 500 | 3 locations (70% head office, 25% warehouse), 8 departments, 16 teams. A few people write most posts. `load-user` is an ordinary colleague, `load-admin` a superuser, so a moderator who sees everything. |
| Groups | 60 | From 400 members down to 15; one in four private. People are in 5 or 6 on average. |
| Posts | 20,000 over 12 months | 400 news (30% for chosen teams), 400 polls, 300 events, and updates: 45% for everyone, 30% for a location, department or team, 25% in groups, 15% with photos. 15 pinned. |
| Comments | 100,000 | Median 2 per post. The pinned posts, which everyone comments on, have 400 to 590 each. One in five is a reply: most threads have none or one, but the newest thread under each pinned post is a conversation of 60 to 200 replies, which the feed shows. |
| Reactions | 100,000 on posts, 20,000 on comments | Up to 384 on one post. |
| News reads | 120,000 | 40% to 80% of staff open each news item. |
| Chats | 2,000 | 1,700 one-to-one and 300 group chats of 3 to 15 people, with 50,000 messages; the busiest has 2,287. One person in five has unread messages. |
| Alerts | 30,000 | Over 90 days (older ones are removed every night); 15% unread. |
| Files | 1,000 | In 40 folders, a third of them for groups. |

A year of this is 79 MB in SQLite, not counting uploads. Expect about twice that in Postgres.

## Before and after

Measured on 20 Nov 2026 on a Windows laptop with SQLite, `DEBUG` on and other work running, all on the same
`seed_load` data. "Before" is the hub as it was before this work, "after" is with the fixes below. Each time is the
fastest of 7 openings, in milliseconds. The live server (Linux, Postgres, `DEBUG` off) will be quicker; what
matters is the change.

| Page | Colleague before | after | Moderator before | after | Queries before → after | Database ms before → after | KB before → after |
|---|--:|--:|--:|--:|--:|--:|--:|
| Feed | 3236 | 400 | 2949 | 463 | 38 → 42 | 106 → 122 | 3173 → 412 |
| Feed, recent activity | 3260 | 448 | 3461 | 466 | 38 → 42 | 132 → 117 | 3210 → 448 |
| Post with the most comments | 908 | 194 | 1034 | 181 | 19 → 24 | 19 → 29 | 1784 → 269 |
| News | 207 | 59 | 290 | 55 | 11 → 11 | 174 → 28 | 18 → 18 |
| Notifications | 29 | 32 | 33 | 39 | 7 → 7 | 8 → 8 | 20 → 20 |
| Chat list | 30 | 27 | 34 | 33 | 9 → 9 | 8 → 8 | 11 → 11 |
| Busiest chat | 48 | 56 | 48 | 43 | 14 → 14 | 17 → 17 | 42 → 42 |
| Chat: check for new messages | 6 | 5 | 6 | 5 | 4 → 4 | 2 → 2 | 0 → 0 |
| Groups | 37 | 40 | 41 | 39 | 7 → 7 | 12 → 13 | 29 → 29 |
| Busiest group | 993 | 324 | 1015 | 350 | 41 → 51 | 108 → 77 | 1078 → 371 |
| People | 31 | 30 | 31 | 32 | 10 → 10 | 11 → 9 | 15 → 15 |
| Profile of the busiest poster | 765 | 257 | 852 | 302 | 22 → 27 | 49 → 52 | 941 → 314 |
| Events | 29 | 31 | 33 | 41 | 8 → 8 | 10 → 11 | 12 → 12 |
| Search | 69 | 86 | 65 | 65 | 16 → 16 | 26 → 28 | 30 → 30 |
| Recent files | 44 | 39 | 38 | 39 | 8 → 8 | 12 → 11 | 19 → 19 |
| Insights (moderator) | - | - | 140 | 147 | 49 → 49 | 101 → 98 | 9 → 9 |
| Admin: posts (moderator) | - | - | 216 | 109 | 63 → 9 | 52 → 9 | 95 → 95 |
| Admin: reports (moderator) | - | - | 156 | 59 | 88 → 8 | 52 → 9 | 42 → 42 |

Queries, database time and size are the colleague's, or the moderator's for the last three rows. Differences of
10 to 20 ms either way are noise on this laptop.

The feed and post pages run a few more queries than before, because they now fetch only what they show, in a few
small steps, instead of everything in one go. The query counts stay the same however long a post's discussion grows.
So does the amount each page loads: a card brings at most 3 threads with 3 replies each, and a post's page 50
threads with 20 replies each. Only "View all comments" (`?comments=all`) shows a whole discussion, because that is
what it is for.

A first round of fixes capped the threads but still brought every reply in each shown thread. On this data, that
left the feed at 1,984 ms and 3.2 MB, and the post page at 742 KB: one long thread under a pinned post grew every
feed. Capping the replies too took the feed to 400 ms and 412 KB.

Opening a news cover or a comment picture also got faster: the check of who may see it took 46 ms and 42 ms, and
now takes 3 ms and 1 ms.

## What was slow, and the fix

1. **Post cards loaded every comment, reply and reaction.** A card shows the two newest comment threads, but the
   hub loaded all of them, with all their replies and reactions. The pinned posts on top of the feed have 400 to 590
   comments each, so the feed built about 2,500 comments to show a few dozen. Cards now load the three newest threads (the
   third tells the card there are more), each with its three newest replies, and count comments and reactions in
   the database (`post_queryset` and `decorate` in `hub/views.py`). A longer thread ends in "View *n* more replies",
   which opens the post.
2. **A post's own page drew every comment.** That was 1.8 MB for one page. It now shows the newest 50 threads, with
   "View all *n* comments" above them, and the newest 20 replies in each, with "View *n* more replies". Both open the
   whole discussion (`?comments=all`). An alert that links to an older comment or reply opens the whole discussion
   by itself (`hub/static/hub/app.js`).
3. **Who-may-see-this checks repeated rows.** They joined the audiences table, then removed the repeats with
   `DISTINCT` over whole posts, on every feed, news list and the News badge. They are subqueries now
   (`PostQuerySet._audience` and `Post.for_everyone` in `hub/models.py`).
4. **News counted reactions and comments with two joined counts.** Those multiply: a news item with 300 of each
   made 90,000 rows to count. They are subqueries now (`PostQuerySet.counting`).
5. **The admin's lists of posts, reports and events fetched each row's group or reported item one at a time:** 63
   and 88 queries for one page. They are fetched together now (`list_select_related` in `hub/admin.py`).
6. **Missing indexes** (migration `hub 0007_performance_indexes`):
   - A post's newest threads (post, parent, time). Without it, SQLite read all 80,000 top-level comments through
     the parent index to find a few posts' threads.
   - News covers and comment pictures, which are looked up on every picture request.

Each fix has a test in `hub/tests_performance.py`:

- The feed, groups, profiles, news, chat list and admin lists run the same number of queries for 2 or 6 of
  everything, each under a ceiling.
- The busiest post runs the same number for 12 or 96 comments.
- Cards load three threads and the post page fifty.
- A thread with 60 replies draws 3 of them on a card and 20 on the post page, with the same queries as one with 2,
  and all 60 with `?comments=all`.
- News for two of my teams shows and counts once.
- `seed_load` and `benchmark` run end to end. `seed_load` refuses a database that has people but no posts yet.

## Looked at and left alone

- **The red badges on every page** (Notifications, News, Chat) take about 5 ms together. They aren't cached: a cached
  number would lag behind what people have just read, and a cache all workers share lives in the database too, so it
  would cost a query of its own.
- **The busiest chat** already shows at most 200 messages; it takes 40 to 120 ms.
- **Insights** runs 49 queries, but for a fixed 10 news items, for admins only.
- **"View all comments"** (`?comments=all`) has no ceiling: it is the one page meant to show a whole discussion. At
  1,500 comments it would take a few seconds. If a discussion ever gets that long, page it.
- **Counting each thread's replies** returns one small row per thread that has replies, from the same query that
  counts each post's comments. That is a few hundred rows for the busiest posts.
- **What's left on the feed and group pages is drawing about 25 post cards** (10 to 15 ms each here, 15 KB of
  page each). Each card has six reaction buttons as small forms, two comments with six more each, and icons picked
  from a long list of `if`s in `hub/templates/hub/_icon.html`. If these pages ever need to be faster, make the
  reaction picker one form and the icon a lookup.
- **The group page decorates its pinned posts and its other posts separately**, about 10 small queries more than
  needed, because the QA team changed the same lines. The feed does both in one `decorate` call; the group
  page can do the same once both changes are in.

## Server settings for 500 staff

The server is the one the README asks for: 2 CPUs, 4 GB of memory.

### gunicorn: 3 workers with 8 threads each (Dockerfile). Keep them.

- Python runs one thread at a time in each process, so CPU work needs processes. Three keep both CPUs busy, with one
  spare while another waits for the database.
- Threads cover the waiting: database calls, and videos being cleaned (ffmpeg runs outside Python). nginx receives
  uploads in full before passing them on, so a slow phone connection doesn't hold a thread.
- 3 × 8 = 24 requests at once. The rush needs about 5 pages, 20 chat checks and up to 100 pictures a second (below).
- One worker used 80 MB here after opening every page. Allow up to 200 MB each: photo uploads are held in memory
  while they are cleaned.
- With 4 CPUs, use 5 workers: change `--workers` in the Dockerfile's last line, then `docker compose up -d --build`.

### Postgres (docker-compose.yml, the `db` service)

| Setting | Value | Why |
|---|---|---|
| `shared_buffers` | 1GB | A quarter of the memory. Years of data fit, so pages are served from memory. |
| `effective_cache_size` | 2GB | Tells the planner how much the operating system caches as well. It takes no memory. |
| `work_mem` | 16MB | Room for each sort, such as picking each post's newest comments and replies. 24 connections × 16 MB still fits easily. |
| `maintenance_work_mem` | 256MB | Faster index building (migrations) and clean-up (vacuum). |
| `random_page_cost` | 1.1 | The disk is an SSD, so the planner should use indexes freely. |
| `shared_preload_libraries` | pg_stat_statements | Keeps a running total of time per query, with the values left out, so slow queries can be found without logging what staff typed (below). It takes a few MB. |
| `shm_size` (Docker) | 256mb | Docker's 64 MB is too little for Postgres's parallel queries, which then fail with "could not resize shared memory segment". |
| `max_connections` | 100 (the default) | The app holds at most 24 (one per thread); the scheduler and backups add a few. |

They apply when the database container starts (`docker compose up -d db`).

The `psql` commands on this page sign in as the database's superuser, `postgres`, which works only inside the `db`
container. The app's own database accounts can't see other sessions or change settings. On a server installed
before the database accounts were split (its `docker-compose.yml` still has `POSTGRES_USER: hub`), the superuser is
`hub`: use `-U hub` there instead.

Check a setting with `docker compose exec db psql -U postgres hub -c "SHOW shared_buffers"`. On an 8 GB server use
2GB and 5GB for the first two.

To find the slowest queries, turn on the totals once, then read them:

```bash
docker compose exec db psql -U postgres hub -c "CREATE EXTENSION IF NOT EXISTS pg_stat_statements"
docker compose exec db psql -U postgres hub -c "SELECT calls, round(mean_exec_time) AS ms, left(query, 120) FROM pg_stat_statements ORDER BY total_exec_time DESC LIMIT 10"
docker compose exec db psql -U postgres hub -c "SELECT pg_stat_statements_reset()"   # start counting again
```

The totals hold each query's shape, with `$1` in place of every value, so no staff words or sign-in keys. Don't turn
on `log_min_duration_statement` instead. It writes whole queries, values included, into the database's log. That
includes sign-in session keys, which would let anyone who reads the log act as that person.

## The 9am rush

An estimate, to compare with what you see in the first weeks:

- About 350 people open the hub between 8:50 and 9:10. Each opens about 6 pages in the first few minutes. The
  busiest minute has about 300 page views, 5 a second.
- Pictures come through the app too: it checks who may see each one (1 to 3 ms), then nginx sends the file. A feed
  asks for about 10 to 20 pictures the first time each day; browsers keep them for a day after that. That is up to
  100 picture requests a second at the peak.
- About 80 people have a chat open. It checks for new messages every 4 seconds: 20 checks a second, 5 ms each.
- A page costs about 0.15 s of CPU on average here (the feed about 0.4 s, most others under 0.07 s). That is
  5 × 0.15 + 100 × 0.003 + 20 × 0.005, about 1.2 CPU-seconds a second: a little over half of the 2 CPUs.
- A company-wide announcement at 9:00 creates 500 alerts in one go. The scheduler then sends about 600 push messages,
  one after another: expect about a minute, depending on Apple's and Google's push services. Event reminders due in
  that minute go out just after.
- nginx counts pages, pictures and chat checks together for each address: 50 a second on average, plus a burst of up
  to 200 more, before it answers "Too many requests". People who reach the hub through one shared address, such as
  warehouse tablets, share that. One feed with its pictures is about 20 requests, so ten people behind one address
  opening the feed in the same second already reach the burst. 100 open chats on one address use 25 a second of the
  50.

What to watch at 9am, in the first weeks and after big changes:

- **CPU used by the app:** `docker stats --no-stream`. Fine under 150% (both CPUs together are 200%). Over 160% for
  10 minutes: add CPUs, then workers (above).
- **Errors and timeouts:** `docker compose logs --since 30m web | grep -E '" 50[24] '` should show nothing. Each line
  it shows names the page that failed or was too slow. `docker compose logs app` only says `WORKER TIMEOUT`, without
  the page.
- **"Too many requests":** `docker compose logs --since 30m web | grep -c '" 429 '`. A handful is fine. Many from one
  address means that address is shared: raise the limit for it in `deploy/nginx.conf`.
- **Database connections:** `docker compose exec db psql -U postgres hub -c "SELECT count(*) FROM pg_stat_activity"`.
  Fine under 40. Over 80: look for stuck queries with
  `docker compose exec db psql -U postgres hub -c "SELECT pid, now() - query_start AS running, state, usename FROM pg_stat_activity ORDER BY 2 DESC NULLS LAST"`.
  It must run as `postgres`: as any other account, the state and time of the app's sessions come back empty and
  nothing looks stuck.
- **Slow queries:** the `pg_stat_statements` list above, read after the rush and reset.
- **Memory:** `free -m`. Some should be free and no swap used. If swap is used, add memory, or go back to fewer
  workers.
- **Push delay:** `docker compose logs --since 30m scheduler | grep pushed` shows a line for each busy minute. If the
  same alerts are still going out 5 minutes later, check that the server can reach the push services (README,
  outbound HTTPS).

The uptime check and the alert emails are in `docs/operations/MONITORING.md`.

## Check again on Postgres

These were measured on SQLite. Before go-live, on a throwaway Postgres (the `hub-load` steps under "Measure it
yourself"), never the test or the live hub:

1. Run `seed_load` and `benchmark` there, and add the table to this page. Expect most pages to be quicker.
2. Run `benchmark --sql`, then `EXPLAIN ANALYZE` the feed's count and its newest-threads and newest-replies queries.
   The threads should use `hub_comment_post_id_4a4e21_idx` and the replies the parent index
   (`hub_comment_parent_id_...`), each taking a few milliseconds.
3. The audience checks (`EXISTS`, `IN`) should become hashed subplans, and the feed's count should stay under 20 ms.
4. News counts are subqueries in the select list. Postgres works them out only for the 20 items shown; SQLite does
   it for every row. Check the News page's database time.
5. The thread index was needed because SQLite keeps no statistics about its tables. Postgres gathers them by itself
   (autovacuum); run `ANALYZE` once after `seed_load` so the test doesn't wait for it.
6. Note memory per worker (`docker stats`) and connections (`pg_stat_activity`) while the benchmark runs, and the
   `pg_stat_statements` list afterwards.

Approval: Signed off (assumed for delivery, 2026-11-20).
