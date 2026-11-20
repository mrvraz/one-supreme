# Feature plan: matching and beating the current TeamSupreme app

Source: a screen recording of the app Supreme uses today (the Speakap platform, white-labelled as "TeamSupreme"),
reviewed on 12 November 2026. Only features and structure were noted. No staff names, posts or messages were kept.
We build the same features in our own design and wording. We do not copy their artwork, text or layout pixel for pixel.

## 1. What their app has, and what we build

Legend: **Have** = already in Staff Hub. **Build** = being added now. **Later** = not built yet, with the reason.

| Area | Their app | Ours |
|---|---|---|
| Main tabs | Feed, Chat, News (unread badge), Notifications, Menu | **Build**: the same five tabs |
| Feed | Sort by activity or newest; filter by scope and by type (posts, news, events, polls) | **Build** |
| Feed | Several pinned items at the top, colour-coded by type | **Build** |
| Posts | Text with bold, italic, strikethrough; photos; "Show more" | **Build** (photos and videos: Have) |
| Posts | Six reactions (like, love, celebrate, laugh, wow, sad) on posts and comments; list of who reacted | **Build** (four reactions: Have) |
| Posts | Comments with replies and likes | **Build** (comments: Have) |
| Posts | Menu: copy text, pin, turn on notifications, report post, report user; "Edited" marker | **Build** (report post: Have) |
| Posts | Polls | **Build** |
| Posts | GIFs from Giphy in posts and comments | **Build** as GIF and photo upload in posts and comments. Giphy search is **Later**: it sends what staff type to Giphy. |
| Posts | "See translation" | **Build**, switched on only when a translation server is configured (self-hosted LibreTranslate keeps data on Supreme's servers) |
| Posts | Scheduled posts and a "Scheduled posts" list | **Build** |
| Posts | Mentions | **Build** |
| News | Separate news items: title, cover, several audiences, drafts, scheduling, "must acknowledge", read ticks, unread filter | **Build**, plus read and acknowledgement counts for the publisher (better) |
| Chat | One-to-one and group chats, people picker | **Build** (app `chat`) |
| Notifications | List, "Mark all as read", accept or decline group invitations inline | **Build** (list: Have) |
| Notifications | Per-type push and email switches, do not disturb (now, and on a schedule), push privacy level | **Build**. Push uses Web Push: works once staff add the hub to their home screen. |
| Menu | Profile header with do-not-disturb switch; list of sections | **Build** |
| Recruitment | A menu shortcut to a group with job adverts | **Build** a proper jobs board (app `jobs`) (better) |
| Knowledge base | Searchable articles | **Build** (app `library`) |
| Journeys | Assigned step-by-step paths with progress; all / incomplete / completed | **Build** (app `journeys`), plus completion figures for editors (better) |
| Featured | Curated links and files, company-wide and per group | **Build** (app `library`) |
| Events | Upcoming / past / my reply filter, create, search, reminders with a personal default | **Build** (events, RSVP, calendar file: Have) |
| Files | Folders and files for the company, per group, and recent | **Build** (app `library`) |
| Organisation | Business units and teams with member counts | **Build** |
| People | Search, filter by team and location; profile with cover, pronouns, languages, bio, Message button | **Build** (directory and search: Have) |
| Groups | Public and private groups, invitations, join requests, tabs Feed / Featured / Members / Files, cover | **Build** (open groups: Have) |
| Birthdays | Upcoming birthdays with a message button | **Build**, plus work anniversaries (better). Opt-in: only shown if the person adds their birthday. |
| Settings | Profile, notifications, event reminders, privacy | **Build**, plus appearance (Daylight / Daylight Dark / match my device) |
| About | Version, what's new with walkthroughs, support, legal documents, system status, licences | **Build** version, what's new, support link, legal, licences. A vendor status page does not apply: the hub runs on Supreme's own servers. |
| Search | Global search with suggestions; search inside each section | **Build** |
| Look | Dark theme | **Build** Hiveshire's Daylight (light) and Daylight Dark looks |
| Safety | Report post, report user | **Have** and more: moderation desk, audit log, evidence kept 30 days, activity limits, house rules, data export, retention |
| Tasks | Assignable tasks with due dates (only seen in their settings; not in Supreme's menu) | **Later**: Supreme does not appear to use it |
| Several networks | Network switcher | **Later**: one hub per company; business units are covered by Organisation |
| Admin analytics | "Compass" analytics | **Build** a simple Insights page for admins |
| AI assistant | Mentioned in their help pages | **Later**: needs a data-protection decision first |

## 2. How the code is organised

- `hub/` — accounts, feed, posts, news, polls, groups and organisation, events, people, notifications, settings, search, moderation.
- `chat/`, `library/` (knowledge base, files, featured), `journeys/`, `jobs/` — one Django app each. They only depend on `hub`.
- `hub/plugins.py` — small hooks so those apps can add search results, menu entries, data-export sections, clean-up jobs,
  nav badges and file-access rules without `hub` importing them.

Rules for every app:

1. Every page needs sign-in (already enforced by middleware). Every write is a POST with the CSRF token.
2. Check permission on the server for every action. Never trust a hidden form field or a link.
3. Never mark user text as safe. Use `{{ text|rich }}` (from `{% load hubtags %}`) for formatted text; it escapes first.
4. Uploads go through `hub.media.process_upload` (photos, videos) or `library.files.check_document` (documents).
   Files are served only by `hub.views.media`, which asks the guard registered for the file's top folder.
5. Tell people with `hub.models.notify(recipients, actor, message, url, category=...)`.
6. Log security-relevant actions with `hub.security.audit(...)`; limit floods with `hub.security.over_limit(...)`.
7. Plain English in the interface. Short sentences. No jargon.
8. No new dependencies without a strong reason.

## 3. Page building blocks (CSS classes in `hub/static/hub/app.css`)

Templates extend `hub/base.html` and fill `{% block content %}`. Pass `nav` in the context as one of
`feed`, `chat`, `news`, `alerts`, `menu` to highlight the tab.

| Class | Use |
|---|---|
| `.page-head` with `h1` and optional buttons | Title row at the top of a page |
| `.back` | "← Back" link above the title on sub-pages |
| `.narrow` | Wrap a single-column page (max 680px) |
| `.card` | Frosted panel. `.card.flat` for a panel without padding (lists) |
| `.list` + `.row` | Grouped rows. A `.row` holds `.row-icon`, `.row-body` (`.row-title`, `.row-sub`), `.row-side` |
| `.chips` + `.chip` (`.chip.on` when selected) | Horizontal filter chips (links or buttons) |
| `.btn`, `.btn.primary`, `.btn.danger`, `.btn.small`, `.btn.wide`, `.icon-btn` | Buttons |
| `.field` with `label` | Form field. Use `{% include "hub/_form_fields.html" %}` to render a whole form |
| `.switch` | Label with a checkbox drawn as an on/off switch |
| `.pill`, `.pill.red`, `.pill.green`, `.pill.orange`, `.pill.grey` | Small status label |
| `.badge` | Red count bubble |
| `.empty` | Empty state inside a card: add `.empty-title` and a short hint |
| `.progress` > `i` (style width) | Progress bar |
| `.avatar` via `{% include "hub/_avatar.html" with u=person size=40 %}` | Avatar with initials fallback |
| `.muted`, `.small`, `.sr-only` | Text helpers |
| `.section-title` | Heading between blocks |
| `.dropdown` (a `details` element) + `.menu` | Small menus |
| `.msg`, `.msg.error` | Inline notices |
| `{% include "hub/_icon.html" with name="..." %}` | Line icons |
| `{% include "hub/_pager.html" %}` | Paging for a `page` object |

Colours come from CSS variables (`--text`, `--muted`, `--accent`, `--accent-strong`, `--surface`, `--surface-2`,
`--line`, `--red`, `--green`, `--orange`). Never hard-code a colour: both looks must work.

## 4. Progress

See the README for what is finished. This file is the reference for why each feature exists.
