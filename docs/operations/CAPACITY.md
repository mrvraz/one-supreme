# Capacity for 500 staff

How fast the hub stays after a year of use by about 500 staff, the server settings that go with it, and what to
watch at the 9am rush.

## Measure it yourself

Two commands do it. `seed_load` fills an empty database with a year of made-up use. `benchmark` opens the 15
busiest pages as an ordinary colleague and as a moderator, and prints a table of times and database queries.

On your computer, with a scratch folder for the database (never your real one):

```bash
export DATA_DIR=/tmp/hub-load DEBUG=1
python manage.py migrate
python manage.py seed_load        # about a minute
python manage.py benchmark        # about two minutes; --sql also shows each page's slowest query
```

On a test server with Postgres, on its own database and never the live hub:
`docker compose exec app python manage.py seed_load --force`, then `docker compose exec app python manage.py benchmark`.
`seed_load` refuses a database that already has posts. The benchmark opens pages like a person would (opening a
chat marks it read), signs in as two made-up accounts, and needs `/admin/` to be open to the server itself for its
three admin pages.

### What seed_load makes

All made up: names put together from short word lists, `example.com` addresses, and file names with no file behind
them. Nobody can sign in as these people.

| What | How many | Shape |
|---|--:|---|
| Staff | 500 | 3 locations (70% head office, 25% warehouse), 8 departments, 16 teams. A few people write most posts. `load-user` is an ordinary colleague, `load-admin` a superuser, so a moderator who sees everything. |
| Groups | 60 | From 400 members down to 15; one in four private. People are in 5 or 6 on average. |
| Posts | 20,000 over 12 months | 400 news (30% for chosen teams), 400 polls, 300 events, and updates: 45% for everyone, 30% for a location, department or team, 25% in groups, 15% with photos. 15 pinned. |
| Comments | 100,000 | One in five is a reply. Median 2 per post; the pinned announcements, which everyone comments on, have 320 to 400 each. |
| Reactions | 100,000 on posts, 20,000 on comments | Up to 395 on one post. |
| News reads | 120,000 | 40% to 80% of staff open each news item. |
| Chats | 2,000 | 1,700 one-to-one and 300 group chats of 3 to 15 people, with 50,000 messages; the busiest has 1,648. One person in five has unread messages. |
| Alerts | 30,000 | Over 90 days (older ones are removed every night); 15% unread. |
| Files | 1,000 | In 40 folders, a third of them for groups. |

A year of this is 83 MB in SQLite, not counting uploads. Expect about twice that in Postgres.

## Before and after

Measured on 20 Nov 2026 on a Windows laptop with SQLite, `DEBUG` on and other work running. Each number is the
fastest of 7 openings, in milliseconds. The live server (Linux, Postgres, `DEBUG` off) will be quicker. What
matters is the change, and that no page now does more work as the data grows.

| Page | Colleague before | after | Moderator before | after | Queries before → after | Database ms before → after |
|---|--:|--:|--:|--:|--:|--:|
| Feed | 1108 | 195 | 1214 | 393 | 38 → 42 | 101 → 55 |
| Feed, recent activity | 1246 | 310 | 998 | 332 | 38 → 42 | 108 → 86 |
| Post with the most comments | 652 | 93 | 557 | 127 | 19 → 24 | 19 → 14 |
| News | 498 | 60 | 548 | 68 | 11 → 11 | 467 → 28 |
| Notifications | 27 | 27 | 32 | 33 | 7 → 7 | 7 → 6 |
| Chat list | 27 | 36 | 34 | 29 | 9 → 9 | 7 → 8 |
| Busiest chat | 35 | 39 | 62 | 55 | 14 → 14 | 12 → 13 |
| Chat: check for new messages | 4 | 5 | 6 | 5 | 4 → 4 | 1 → 2 |
| Groups | 28 | 45 | 45 | 39 | 7 → 7 | 8 → 14 |
| Busiest group | 518 | 333 | 518 | 207 | 41 → 51 | 51 → 80 |
| People | 30 | 34 | 28 | 24 | 10 → 10 | 10 → 10 |
| Profile of the busiest poster | 376 | 233 | 384 | 246 | 22 → 27 | 48 → 47 |
| Events | 31 | 39 | 31 | 35 | 8 → 8 | 12 → 15 |
| Search | 60 | 73 | 64 | 57 | 16 → 16 | 27 → 28 |
| Recent files | 37 | 48 | 33 | 31 | 8 → 8 | 12 → 14 |
| Insights (moderator) | - | - | 143 | 142 | 49 → 49 | 99 → 99 |
| Admin: posts (moderator) | - | - | 184 | 85 | 63 → 9 | 50 → 7 |
| Admin: reports (moderator) | - | - | 160 | 52 | 88 → 8 | 53 → 8 |

Queries and database time are the colleague's, or the moderator's for the last three rows. Differences of 10 ms
either way are noise on this laptop.

Opening a news cover or a comment picture also got faster: the check of who may see it took 46 ms and 42 ms, and
now takes 3 ms and 1 ms.

## What was slow, and the fix

1. **Post cards loaded every comment and reaction.** A card shows the two newest comment threads, but the hub loaded
   all of them, with their reactions. The five pinned announcements on top of the feed have about 350 each, so the
   feed built about 2,000 comments to show 50. Cards now load the three newest threads (the third tells the card
   there are more), and count comments and reactions in the database (`post_queryset` and `decorate` in
   `hub/views.py`).
2. **A post's own page drew every comment.** That was 400 comments and 3,700 links for one page. It now shows the
   newest 50 threads, with "View all *n* comments" above them. An alert that links to an older comment opens the
   full list by itself (`hub/static/hub/app.js`).
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
- News for two of my teams shows and counts once.
- `seed_load` and `benchmark` run end to end.

## Looked at and left alone

- **The red badges on every page** (Notifications, News, Chat) take about 5 ms together. They aren't cached: a cached
  number would lag behind what people have just read, and a cache all workers share lives in the database too, so it
  would cost a query of its own.
- **The busiest chat** already shows at most 200 messages; it takes 40 to 120 ms.
- **Insights** runs 49 queries, but for a fixed 10 news items, for admins only.
- **What's left on the feed and group pages is drawing about 25 post cards** (5 to 10 ms each here). Each card has
  six reaction buttons as small forms, two comments with six more each, and icons picked from a long list of
  `if`s in `hub/templates/hub/_icon.html`. If these pages ever need to be faster, make the reaction picker one form and the icon
  a lookup.
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
- 3 × 8 = 24 requests at once. The rush needs about 5 pages and 20 chat checks a second (below).
- One worker used 80 MB here after opening every page. Allow up to 200 MB each: photo uploads are held in memory
  while they are cleaned.
- With 4 CPUs, use 5 workers: change `--workers` in the Dockerfile's last line, then `docker compose up -d --build`.

### Postgres (docker-compose.yml, the `db` service)

| Setting | Value | Why |
|---|---|---|
| `shared_buffers` | 1GB | A quarter of the memory. Years of data fit, so pages are served from memory. |
| `effective_cache_size` | 2GB | Tells the planner how much the operating system caches as well. It takes no memory. |
| `work_mem` | 16MB | Room for each sort, such as picking each post's newest comments. 24 connections × 16 MB still fits easily. |
| `maintenance_work_mem` | 256MB | Faster index building (migrations) and clean-up (vacuum). |
| `random_page_cost` | 1.1 | The disk is an SSD, so the planner should use indexes freely. |
| `shm_size` (Docker) | 256mb | Docker's 64 MB is too little for Postgres's parallel queries, which then fail with "could not resize shared memory segment". |
| `max_connections` | 100 (the default) | The app holds at most 24 (one per thread); the scheduler and backups add a few. |

They apply when the database container starts (`docker compose up -d db`). Check one with
`docker compose exec db psql -U hub -c "SHOW shared_buffers"`. On an 8 GB server use 2GB and 5GB for the first two.

Slow queries are not logged by default, because Postgres would write each query, with what staff typed, into the
log. To find slow queries for a day, turn logging on, then off again, and treat that log as staff data:

```bash
docker compose exec db psql -U hub -c "ALTER SYSTEM SET log_min_duration_statement = 500" -c "SELECT pg_reload_conf()"
docker compose exec db psql -U hub -c "ALTER SYSTEM RESET log_min_duration_statement" -c "SELECT pg_reload_conf()"
```

## The 9am rush

An estimate, to compare with what you see in the first weeks:

- About 350 people open the hub between 8:50 and 9:10. Each opens about 6 pages in the first few minutes. The
  busiest minute has about 300 page views, 5 a second.
- About 80 people have a chat open. It checks for new messages every 4 seconds: 20 checks a second, 5 ms each.
- A page costs about 0.15 s of CPU on average here (the feed 0.2 to 0.4 s, most others under 0.07 s). That is
  5 × 0.15 + 20 × 0.005, under 1 CPU-second a second: less than half of the 2 CPUs.
- A company-wide announcement at 9:00 creates 500 alerts in one go. The scheduler then sends about 600 push messages,
  one after another: expect about a minute, depending on Apple's and Google's push services. Event reminders due in
  that minute go out just after.
- nginx limits each address to 50 page requests a second, 200 at once. People who reach the hub through one shared
  address, such as warehouse tablets, share that limit. 100 open chats on one address use 25 a second.

What to watch at 9am, in the first weeks and after big changes:

- **CPU used by the app:** `docker stats --no-stream`. Fine under 150% (both CPUs together are 200%). Over 160% for
  10 minutes: add CPUs, then workers (above).
- **Errors and timeouts:** `docker compose logs --since 30m web | grep -cE '" 50[24] '` should say 0. If not,
  `docker compose logs app` shows which page was slow.
- **"Too many requests":** `docker compose logs --since 30m web | grep -c '" 429 '`. A handful is fine. Many from one
  address means that address is shared: raise the limit for it in `deploy/nginx.conf`.
- **Database connections:** `docker compose exec db psql -U hub -c "SELECT count(*) FROM pg_stat_activity"`. Fine
  under 40. Over 80: look for stuck queries with
  `SELECT pid, now() - query_start, state FROM pg_stat_activity ORDER BY 2 DESC`.
- **Memory:** `free -m`. Some should be free and no swap used. If swap is used, add memory, or go back to fewer
  workers.
- **Push delay:** `docker compose logs --since 30m scheduler | grep pushed` shows a line for each busy minute. If the
  same alerts are still going out 5 minutes later, check that the server can reach the push services (README,
  outbound HTTPS).

The uptime check and the alert emails are in `docs/operations/MONITORING.md`.

## Check again on Postgres

These were measured on SQLite. Before go-live, on the Postgres test server:

1. Run `seed_load` and `benchmark` there, and add the table to this page. Expect most pages to be quicker.
2. Run `benchmark --sql`, then `EXPLAIN ANALYZE` the feed's count and its newest-threads query. They should use
   `hub_comment_post_id_4a4e21_idx` and take a few milliseconds.
3. The audience checks (`EXISTS`, `IN`) should become hashed subplans, and the feed's count should stay under 20 ms.
4. News counts are subqueries in the select list. Postgres works them out only for the 20 items shown; SQLite does
   it for every row. Check the News page's database time.
5. The thread index was needed because SQLite keeps no statistics about its tables. Postgres gathers them by itself
   (autovacuum); run `ANALYZE` once after `seed_load` so the test doesn't wait for it.
6. Note memory per worker (`docker stats`) and connections (`pg_stat_activity`) while the benchmark runs.

Approval: Signed off (assumed for delivery, 2026-11-20).
