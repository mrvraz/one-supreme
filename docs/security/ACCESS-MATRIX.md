# Access matrix: who can reach what

Every address in the hub, for every kind of person, for a link (GET) and for a form or button (POST).

This document is the rule, and a test holds the code to it. `hub/tests_access_matrix.py` reads the tables below, asks every
address as every person in them, and fails on any answer that differs. It takes the list of addresses from Django itself, so
a new page fails the test until someone adds a row here and so decides who may open it.

**Approval:** Supreme IT security and HR. Signed off (assumed for delivery, 2026-11-20).

## The people in the table

| Column | Who they are | What their role gives them |
|---|---|---|
| Signed out | Nobody is signed in. | Nothing. |
| Leaver | An account switched off after they left, still holding a session from before. | Nothing: the session stops counting at once. |
| New starter | Signed in for the first time, house rules not accepted yet. | The house rules page, signing out, and the files they could see anyway. |
| Colleague | Ordinary staff. Not in the private group or the chat, and wrote none of the records. | What every member of staff has. |
| Member | In the private group and in its group chat. | The same as a colleague. |
| Author | Wrote the poll, the comment, the event and the chat message. Started the private group (so is its admin) and the chat. Is the vacancy's recruiter, and has one alert. | The same as a colleague. |
| Publisher | The Communications role. Wrote the must-read news, sent only to the private group, without being in it. | "Can publish news" and "Can view usage figures". |
| Editor | The Editors role. This is what a manager gets: Supreme's managers have no separate role in the hub. Added the journey and the vacancy. | Add, change and delete files, folders, featured links, articles, categories, journeys and vacancies. |
| Org admin | The Organisation admins role. | Change groups and units. This makes them an admin of every group and unit. |
| Moderator | The Moderators role, with staff status. | View, change and delete posts, comments and reports. View the audit log. |
| Superuser | Superuser and staff status. | Every permission. |

The roles are set up as README.md ("Roles") tells Supreme's IT to set them up. Only the Moderator and the Superuser have staff
status, so only they can get into the admin.

The records belong to a **private group** ("Private project"). The author is its admin and the member is in it; nobody else
is. In it are a poll with a photo and a comment, an event, a folder with a file, a featured link and a group chat. The
colleague has asked to join. There is also a must-read news item for the group, a journey given to the group, a vacancy, an
article and a draft journey with a cover.

## What the answers mean

| Answer | What happens |
|---|---|
| yes | The page opens, or the action is done. |
| hidden | "Not found" (404). They can't even tell it exists. |
| refused | "Forbidden" (403). They may not do this. |
| wrong method | "Method not allowed" (405). A button's address followed as a plain link. Nothing happens. |
| sign in | Sent to the sign-in page. Also after signing out. |
| rules | Sent to the house rules first. |
| view only | In the admin: the page opens, but saving is refused. |

A row with the method POST is a button: the same address followed as a link gets "wrong method" from everyone signed in,
unless the table has a GET row for it too.

## Before signing in, and before the house rules

Signed-out people and leavers are sent to the sign-in page, and new starters to the house rules, everywhere except here.

| Page or action | Address | Method | Signed out | Leaver | New starter |
|---|---|---|---|---|---|
| Start single sign-on | `oidc_authentication_init` | GET | yes | yes | yes |
| Start single sign-on | `oidc_authentication_init` | POST | wrong method | wrong method | wrong method |
| Single sign-on comes back here | `oidc_authentication_callback` | GET | sign in | sign in | sign in |
| Single sign-on comes back here | `oidc_authentication_callback` | POST | wrong method | wrong method | wrong method |
| Sign out (single sign-on) | `oidc_logout` | GET | sign in | sign in | wrong method |
| Sign out (single sign-on) | `oidc_logout` | POST | sign in | sign in | sign in |
| Sign-in page | `login` | GET, POST | yes | yes | yes |
| Sign out | `logout` | GET | sign in | sign in | wrong method |
| Sign out | `logout` | POST | sign in | sign in | sign in |
| Home-screen app details | `manifest` | GET, POST | yes | yes | yes |
| App icon | `icon` | GET, POST | yes | yes | yes |
| Push notification script | `service_worker` | GET, POST | yes | yes | rules |
| House rules: read and accept | `house_rules` | GET, POST | sign in | sign in | yes |
| Uploaded file: a profile photo | `media` (avatars) | GET, POST | sign in | sign in | yes |
| Uploaded file: a picture in a chat | `media` (chat) | GET, POST | sign in | sign in | hidden |
| Uploaded file: a picture on a comment | `media` (comments) | GET, POST | sign in | sign in | hidden |
| Uploaded file: a news cover | `media` (covers) | GET, POST | sign in | sign in | hidden |
| Uploaded file: a draft journey's cover | `media` (journeys) | GET, POST | sign in | sign in | hidden |
| Uploaded file: a file in the private group | `media` (library) | GET, POST | sign in | sign in | hidden |
| Uploaded file: a photo in a post | `media` (posts) | GET, POST | sign in | sign in | hidden |

- In the test there is no real single sign-on, so the way back from it always ends on the sign-in page.
- A new starter can open the files they could see anyway (profile photos), but nothing of the private group.

## Pages and actions

### Sign-in and the app shell

| Page or action | Address | Method | Colleague | Member | Author | Publisher | Editor | Org admin | Moderator | Superuser |
|---|---|---|---|---|---|---|---|---|---|---|
| Start single sign-on | `oidc_authentication_init` | GET | yes | yes | yes | yes | yes | yes | yes | yes |
| Start single sign-on | `oidc_authentication_init` | POST | wrong method | wrong method | wrong method | wrong method | wrong method | wrong method | wrong method | wrong method |
| Single sign-on comes back here | `oidc_authentication_callback` | GET | sign in | sign in | sign in | sign in | sign in | sign in | sign in | sign in |
| Single sign-on comes back here | `oidc_authentication_callback` | POST | wrong method | wrong method | wrong method | wrong method | wrong method | wrong method | wrong method | wrong method |
| Sign out (single sign-on) | `oidc_logout` | POST | sign in | sign in | sign in | sign in | sign in | sign in | sign in | sign in |
| Sign-in page | `login` | GET, POST | yes | yes | yes | yes | yes | yes | yes | yes |
| Sign out | `logout` | POST | sign in | sign in | sign in | sign in | sign in | sign in | sign in | sign in |
| Home-screen app details | `manifest` | GET, POST | yes | yes | yes | yes | yes | yes | yes | yes |
| App icon | `icon` | GET, POST | yes | yes | yes | yes | yes | yes | yes | yes |
| Push notification script | `service_worker` | GET, POST | yes | yes | yes | yes | yes | yes | yes | yes |
| House rules: read and accept | `house_rules` | GET, POST | yes | yes | yes | yes | yes | yes | yes | yes |
| Uploaded file: a profile photo | `media` (avatars) | GET, POST | yes | yes | yes | yes | yes | yes | yes | yes |
| Uploaded file: a picture in a chat | `media` (chat) | GET, POST | hidden | yes | yes | hidden | hidden | hidden | hidden | hidden |
| Uploaded file: a picture on a comment | `media` (comments) | GET, POST | hidden | yes | yes | hidden | hidden | hidden | yes | yes |
| Uploaded file: a news cover | `media` (covers) | GET, POST | hidden | yes | yes | yes | hidden | hidden | yes | yes |
| Uploaded file: a draft journey's cover | `media` (journeys) | GET, POST | hidden | hidden | hidden | hidden | yes | hidden | hidden | yes |
| Uploaded file: a file in the private group | `media` (library) | GET, POST | hidden | yes | yes | hidden | hidden | yes | hidden | yes |
| Uploaded file: a photo in a post | `media` (posts) | GET, POST | hidden | yes | yes | hidden | hidden | hidden | yes | yes |

- Every upload folder has its own row, and each file comes from the private group where it can. A file goes only to people
  who may see what it belongs to.
- Moderators see chat pictures only from someone who has been reported, so they can judge the report. Nobody here is.

### Feed and posts

| Page or action | Address | Method | Colleague | Member | Author | Publisher | Editor | Org admin | Moderator | Superuser |
|---|---|---|---|---|---|---|---|---|---|---|
| Home feed, and posting to it | `feed` | GET, POST | yes | yes | yes | yes | yes | yes | yes | yes |
| Open a post | `post_detail` | GET, POST | hidden | yes | yes | hidden | hidden | hidden | yes | yes |
| Who reacted to a post | `post_reactions` | GET, POST | hidden | yes | yes | hidden | hidden | hidden | yes | yes |
| React to a post | `react` | POST | hidden | yes | yes | hidden | hidden | hidden | yes | yes |
| Comment on a post | `comment_create` | POST | hidden | yes | yes | hidden | hidden | hidden | yes | yes |
| Vote in a poll | `poll_vote` | POST | hidden | yes | yes | hidden | hidden | hidden | yes | yes |
| Follow a post | `post_follow` | POST | hidden | yes | yes | hidden | hidden | hidden | yes | yes |
| Edit a post | `post_edit` | GET, POST | hidden | hidden | yes | hidden | hidden | hidden | hidden | hidden |
| Publish a draft or scheduled post now | `post_publish_now` | POST | hidden | hidden | yes | hidden | hidden | hidden | hidden | hidden |
| Pin or unpin a post | `post_pin` | POST | hidden | refused | yes | hidden | hidden | hidden | yes | yes |
| Delete a post | `post_delete` | POST | refused | refused | yes | refused | refused | refused | yes | yes |
| React to a comment | `comment_react` | POST | hidden | yes | yes | hidden | hidden | hidden | yes | yes |
| Delete a comment | `comment_delete` | POST | refused | refused | yes | refused | refused | refused | yes | yes |
| Report a post | `report` (post) | GET, POST | hidden | yes | yes | hidden | hidden | hidden | yes | yes |
| Report a comment | `report` (comment) | GET, POST | hidden | yes | yes | hidden | hidden | hidden | yes | yes |
| Report a person | `report` (person) | GET, POST | yes | yes | hidden | yes | yes | yes | yes | yes |
| See a translation of a post | `translate` (post) | POST | hidden | yes | yes | hidden | hidden | hidden | yes | yes |
| See a translation of a comment | `translate` (comment) | POST | hidden | yes | yes | hidden | hidden | hidden | yes | yes |
| My scheduled posts and drafts | `scheduled` | GET, POST | yes | yes | yes | yes | yes | yes | yes | yes |

- Only the author edits a post or publishes it early. The group's admins (here the author) and moderators pin it.
- Moderators open every post, hidden and deleted ones too, so they can judge reports.
- The person reported can't report themselves.
- Translation needs a translation server (`TRANSLATE_URL`). Without one, everyone gets "hidden".

### News

| Page or action | Address | Method | Colleague | Member | Author | Publisher | Editor | Org admin | Moderator | Superuser |
|---|---|---|---|---|---|---|---|---|---|---|
| News list | `news` | GET, POST | yes | yes | yes | yes | yes | yes | yes | yes |
| Write news | `news_new` | GET, POST | refused | refused | refused | yes | refused | refused | refused | yes |
| Edit news | `news_edit` | GET, POST | refused | refused | refused | yes | refused | refused | refused | yes |
| Confirm I've read must-read news | `news_ack` | POST | hidden | yes | yes | yes | hidden | hidden | yes | yes |
| Who has confirmed must-read news | `news_readers` | GET, POST | hidden | refused | refused | yes | hidden | hidden | refused | yes |

- Writing news needs "Can publish news". Editing someone else's news also needs the moderators' change right.
- Who has confirmed: its author and other publishers who can see it. Its readers are refused, and people it wasn't sent to
  get "hidden", so the list can't show who is in a private group.

### People

| Page or action | Address | Method | Colleague | Member | Author | Publisher | Editor | Org admin | Moderator | Superuser |
|---|---|---|---|---|---|---|---|---|---|---|
| People directory | `people` | GET, POST | yes | yes | yes | yes | yes | yes | yes | yes |
| Name suggestions for @mentions | `people_suggest` | GET, POST | yes | yes | yes | yes | yes | yes | yes | yes |
| A colleague's profile | `profile` | GET, POST | yes | yes | yes | yes | yes | yes | yes | yes |
| Edit my profile | `profile_edit` | GET, POST | yes | yes | yes | yes | yes | yes | yes | yes |
| Download my data | `export_my_data` | GET, POST | yes | yes | yes | yes | yes | yes | yes | yes |
| Birthdays and work anniversaries | `birthdays` | GET, POST | yes | yes | yes | yes | yes | yes | yes | yes |

- "Edit my profile" and "Download my data" are always about the person asking.

### Groups and the organisation

| Page or action | Address | Method | Colleague | Member | Author | Publisher | Editor | Org admin | Moderator | Superuser |
|---|---|---|---|---|---|---|---|---|---|---|
| Groups list | `communities` | GET, POST | yes | yes | yes | yes | yes | yes | yes | yes |
| Start a group | `community_create` | GET, POST | yes | yes | yes | yes | yes | yes | yes | yes |
| A group's page | `community` | GET | yes | yes | yes | yes | yes | yes | yes | yes |
| Post in a group | `community` | POST | refused | yes | yes | refused | refused | refused | refused | refused |
| Edit a group | `community_edit` | GET, POST | refused | refused | yes | refused | refused | yes | refused | yes |
| A group's members, requests and invitations | `community_members` | GET, POST | hidden | yes | yes | hidden | hidden | yes | hidden | yes |
| Remove a member, or make or unmake an admin | `community_member_change` | POST | refused | refused | yes | refused | refused | yes | refused | yes |
| Invite someone to a group | `community_invite` | POST | refused | refused | yes | refused | refused | yes | refused | yes |
| Answer a request to join | `invite_answer` | POST | refused | refused | yes | refused | refused | yes | refused | yes |
| Join a group, or ask to | `community_join` | POST | yes | yes | yes | yes | yes | yes | yes | yes |
| Leave a group | `community_leave` | POST | yes | yes | yes | yes | yes | yes | yes | yes |
| Organisation (units) | `organisation` | GET, POST | yes | yes | yes | yes | yes | yes | yes | yes |

- People outside a private group see its name and description and can ask to join; not its posts, members, events or files.
- Org admins count as an admin of every group and unit, so they open a private group's page, members, events and files and
  run it. Its posts stay with its members unless they join.
- Posting in a group needs membership, for a superuser too.
- The colleague's own request to join is refused when they try to answer it: a group admin must.

### Events

| Page or action | Address | Method | Colleague | Member | Author | Publisher | Editor | Org admin | Moderator | Superuser |
|---|---|---|---|---|---|---|---|---|---|---|
| Events list | `events` | GET, POST | yes | yes | yes | yes | yes | yes | yes | yes |
| Create an event | `event_create` | GET, POST | yes | yes | yes | yes | yes | yes | yes | yes |
| An event | `event` | GET, POST | hidden | yes | yes | hidden | hidden | yes | hidden | yes |
| Add an event to my calendar | `event_ics` | GET, POST | hidden | yes | yes | hidden | hidden | yes | hidden | yes |
| Reply to an event | `rsvp` | POST | hidden | yes | yes | hidden | hidden | yes | hidden | yes |
| My reminders for one event | `event_reminders` | POST | hidden | yes | yes | hidden | hidden | hidden | hidden | hidden |
| Edit an event | `event_edit` | GET, POST | refused | refused | yes | refused | refused | refused | refused | yes |
| Delete an event | `event_delete` | POST | refused | refused | yes | refused | refused | refused | refused | yes |

- Reminders for one event need a reply to it first (the author and the member have said they're going).
- Only the organiser edits or deletes an event, plus anyone given the change or delete right for events in the admin.

### Alerts, settings, search and about

| Page or action | Address | Method | Colleague | Member | Author | Publisher | Editor | Org admin | Moderator | Superuser |
|---|---|---|---|---|---|---|---|---|---|---|
| My alerts | `notifications` | GET, POST | yes | yes | yes | yes | yes | yes | yes | yes |
| Open one alert | `notification_open` | GET, POST | hidden | hidden | yes | hidden | hidden | hidden | hidden | hidden |
| Mark all my alerts read | `notifications_read_all` | POST | yes | yes | yes | yes | yes | yes | yes | yes |
| Do not disturb on or off | `dnd_toggle` | POST | yes | yes | yes | yes | yes | yes | yes | yes |
| Light or dark look | `look_switch` | POST | yes | yes | yes | yes | yes | yes | yes | yes |
| Turn on push on this device | `push_subscribe` | POST | yes | yes | yes | yes | yes | yes | yes | yes |
| Turn off push on this device | `push_unsubscribe` | POST | yes | yes | yes | yes | yes | yes | yes | yes |
| Send me a test push | `push_test` | POST | yes | yes | yes | yes | yes | yes | yes | yes |
| Menu | `menu` | GET, POST | yes | yes | yes | yes | yes | yes | yes | yes |
| Search | `search` | GET, POST | yes | yes | yes | yes | yes | yes | yes | yes |
| Search suggestions | `search_suggest` | GET, POST | yes | yes | yes | yes | yes | yes | yes | yes |
| Settings | `settings` | GET, POST | yes | yes | yes | yes | yes | yes | yes | yes |
| Notification settings | `settings_notifications` | GET, POST | yes | yes | yes | yes | yes | yes | yes | yes |
| Reminder settings | `settings_reminders` | GET, POST | yes | yes | yes | yes | yes | yes | yes | yes |
| Privacy settings | `settings_privacy` | GET, POST | yes | yes | yes | yes | yes | yes | yes | yes |
| Appearance settings | `settings_appearance` | GET, POST | yes | yes | yes | yes | yes | yes | yes | yes |
| About | `about` | GET, POST | yes | yes | yes | yes | yes | yes | yes | yes |
| What's new | `whats_new` | GET, POST | yes | yes | yes | yes | yes | yes | yes | yes |
| Licences | `licences` | GET, POST | yes | yes | yes | yes | yes | yes | yes | yes |
| Insights (usage figures) | `insights` | GET, POST | refused | refused | refused | yes | refused | refused | refused | yes |

- Everything here except Insights is about the person asking. One alert belongs to the author; nobody else can open it.
- Search only finds what the person may open.

### Chat

| Page or action | Address | Method | Colleague | Member | Author | Publisher | Editor | Org admin | Moderator | Superuser |
|---|---|---|---|---|---|---|---|---|---|---|
| My chats | `chat:list` | GET, POST | yes | yes | yes | yes | yes | yes | yes | yes |
| Start a chat | `chat:new` | GET, POST | yes | yes | yes | yes | yes | yes | yes | yes |
| Open my one-to-one chat with the author | `chat:with` | GET, POST | yes | yes | hidden | yes | yes | yes | yes | yes |
| A chat | `chat:thread` | GET, POST | hidden | yes | yes | hidden | hidden | hidden | hidden | hidden |
| Fetch new messages | `chat:poll` | GET, POST | hidden | yes | yes | hidden | hidden | hidden | hidden | hidden |
| Send a message | `chat:send` | POST | hidden | yes | yes | hidden | hidden | hidden | hidden | hidden |
| Mute a chat | `chat:mute` | POST | hidden | yes | yes | hidden | hidden | hidden | hidden | hidden |
| Leave a group chat | `chat:leave` | POST | hidden | yes | yes | hidden | hidden | hidden | hidden | hidden |
| A group chat's members | `chat:members` | GET | hidden | yes | yes | hidden | hidden | hidden | hidden | hidden |
| Add or remove people in a group chat | `chat:members` | POST | hidden | refused | yes | hidden | hidden | hidden | hidden | hidden |
| Delete a message | `chat:delete_message` | POST | hidden | hidden | yes | hidden | hidden | hidden | hidden | hidden |
| Report a message | `chat:report` | POST | hidden | yes | hidden | hidden | hidden | hidden | hidden | hidden |

- A chat is only for the people in it. Not even a superuser can read it.
- Whoever started a group chat adds and removes people. A message is deleted by its sender and reported by anyone else in the chat.
- Nobody can open a one-to-one chat with themselves.

### Files, featured and knowledge base

| Page or action | Address | Method | Colleague | Member | Author | Publisher | Editor | Org admin | Moderator | Superuser |
|---|---|---|---|---|---|---|---|---|---|---|
| Company files | `library:files` | GET, POST | yes | yes | yes | yes | yes | yes | yes | yes |
| Add a company file | `library:upload` | POST | refused | refused | refused | refused | yes | refused | refused | yes |
| New company folder | `library:folder_new` | POST | refused | refused | refused | refused | yes | refused | refused | yes |
| A group's files | `library:group_files` | GET, POST | hidden | yes | yes | hidden | hidden | yes | hidden | yes |
| Delete a folder in the group | `library:folder_delete` | POST | hidden | refused | yes | hidden | hidden | yes | hidden | yes |
| Delete a file in the group | `library:document_delete` | POST | hidden | refused | yes | hidden | hidden | yes | hidden | yes |
| Feature a file in the group, or stop | `library:document_feature` | POST | hidden | refused | yes | hidden | hidden | yes | hidden | yes |
| Featured links and files | `library:featured` | GET, POST | yes | yes | yes | yes | yes | yes | yes | yes |
| A group's featured links and files | `library:group_featured` | GET, POST | hidden | yes | yes | hidden | hidden | yes | hidden | yes |
| Add a company featured link | `library:link_new` | POST | refused | refused | refused | refused | yes | refused | refused | yes |
| Remove a featured link in the group | `library:link_delete` | POST | hidden | refused | yes | hidden | hidden | yes | hidden | yes |
| Knowledge base | `library:kb` | GET, POST | yes | yes | yes | yes | yes | yes | yes | yes |
| Read an article | `library:article` | GET, POST | yes | yes | yes | yes | yes | yes | yes | yes |
| Legal documents | `library:legal` | GET, POST | yes | yes | yes | yes | yes | yes | yes | yes |
| Write an article | `library:article_new` | GET, POST | refused | refused | refused | refused | yes | refused | refused | yes |
| Edit an article | `library:article_edit` | GET, POST | refused | refused | refused | refused | yes | refused | refused | yes |
| Delete an article | `library:article_delete` | POST | refused | refused | refused | refused | yes | refused | refused | yes |
| Add a category | `library:category_new` | POST | refused | refused | refused | refused | yes | refused | refused | yes |

- Company-wide files, folders and links need the Editor role. Inside a group, its admins decide (here the author, and org
  admins), and an editor's company rights don't reach in.

### Journeys

| Page or action | Address | Method | Colleague | Member | Author | Publisher | Editor | Org admin | Moderator | Superuser |
|---|---|---|---|---|---|---|---|---|---|---|
| My journeys | `journeys:list` | GET, POST | yes | yes | yes | yes | yes | yes | yes | yes |
| A journey | `journeys:detail` | GET, POST | hidden | yes | yes | hidden | yes | hidden | hidden | yes |
| A step | `journeys:step` | GET, POST | hidden | yes | yes | hidden | yes | hidden | hidden | yes |
| Tick a step off | `journeys:step_done` | POST | hidden | yes | yes | hidden | yes | hidden | hidden | yes |
| New journey | `journeys:new` | GET, POST | refused | refused | refused | refused | yes | refused | refused | yes |
| Edit a journey | `journeys:edit` | GET, POST | refused | refused | refused | refused | yes | refused | refused | yes |
| Everyone's progress on a journey | `journeys:progress` | GET, POST | refused | refused | refused | refused | yes | refused | refused | yes |
| Add a step | `journeys:step_new` | GET, POST | refused | refused | refused | refused | yes | refused | refused | yes |
| Edit a step | `journeys:step_edit` | GET, POST | refused | refused | refused | refused | yes | refused | refused | yes |
| Publish or unpublish a journey | `journeys:publish` | GET | refused | refused | refused | refused | wrong method | refused | refused | wrong method |
| Publish or unpublish a journey | `journeys:publish` | POST | refused | refused | refused | refused | yes | refused | refused | yes |
| Delete a journey | `journeys:delete` | GET | refused | refused | refused | refused | wrong method | refused | refused | wrong method |
| Delete a journey | `journeys:delete` | POST | refused | refused | refused | refused | yes | refused | refused | yes |
| Delete a step | `journeys:step_delete` | GET | refused | refused | refused | refused | wrong method | refused | refused | wrong method |
| Delete a step | `journeys:step_delete` | POST | refused | refused | refused | refused | yes | refused | refused | yes |

- The journey is given to the private group, so to the author and the member. Editors open every journey.
- Ticking a step off only counts for people the journey was given to. An editor gets the page back with "This journey has
  not been given to you", so the table says yes.
- The GET rows: these buttons check the role before the method, so a link from someone who isn't an editor is refused.

### Jobs

| Page or action | Address | Method | Colleague | Member | Author | Publisher | Editor | Org admin | Moderator | Superuser |
|---|---|---|---|---|---|---|---|---|---|---|
| Vacancies | `jobs:list` | GET, POST | yes | yes | yes | yes | yes | yes | yes | yes |
| A vacancy | `jobs:detail` | GET, POST | yes | yes | yes | yes | yes | yes | yes | yes |
| Say I'm interested | `jobs:interest` | POST | yes | yes | yes | yes | yes | yes | yes | yes |
| Withdraw my interest | `jobs:withdraw` | POST | yes | yes | yes | yes | yes | yes | yes | yes |
| Who is interested in a vacancy | `jobs:interested` | GET, POST | hidden | hidden | yes | hidden | yes | hidden | hidden | yes |
| Add a vacancy | `jobs:new` | GET, POST | refused | refused | refused | refused | yes | refused | refused | yes |
| Edit a vacancy | `jobs:edit` | GET, POST | refused | refused | refused | refused | yes | refused | refused | yes |
| Close or reopen a vacancy | `jobs:toggle` | GET | refused | refused | refused | refused | wrong method | refused | refused | wrong method |
| Close or reopen a vacancy | `jobs:toggle` | POST | refused | refused | refused | refused | yes | refused | refused | yes |
| Delete a vacancy | `jobs:delete` | GET | refused | refused | refused | refused | wrong method | refused | refused | wrong method |
| Delete a vacancy | `jobs:delete` | POST | refused | refused | refused | refused | yes | refused | refused | yes |

- Who is interested: the recruiter (here the author), whoever added the vacancy, and editors.

## Records that don't exist, and IDs that don't go together

- **Made-up IDs.** Every address with an ID, a group name or a file name is tried again with one that doesn't exist, by
  every signed-in column. Where the table says yes or hidden, the answer must be "hidden". Where it says refused, it may be
  refused or hidden, as some pages check the role before they look the record up. Never yes, and never an error.
- **IDs that don't go together** get "hidden": a step of another journey (open, edit, delete or tick off), and someone who
  isn't in the group (remove, or make an admin). An answer from another poll is a bad request, and no vote is saved.
- **Other people's IDs** are the columns themselves: the colleague, the member and the author all use the same records.

## The admin

The admin is Django's own, with Django's permissions. Only people with staff status get in. Everyone else signed in is
refused, so the admin can't be reached by changing a link.

| Admin page | Address | Method | Signed out | Leaver | New starter | No staff status | Moderator | Superuser |
|---|---|---|---|---|---|---|---|---|
| Admin sign-in (sends you to the hub's sign-in) | `admin_login` | GET, POST | sign in | sign in | rules | refused | yes | yes |
| Django's own admin sign-in (never reached: the one above comes first) | `admin:login` | GET, POST | sign in | sign in | rules | refused | yes | yes |
| Admin home | `admin:index` | GET, POST | sign in | sign in | rules | refused | yes | yes |
| Admin sign-out | `admin:logout` | GET | sign in | sign in | rules | refused | wrong method | wrong method |
| Admin sign-out | `admin:logout` | POST | sign in | sign in | rules | refused | sign in | sign in |
| Change my password | `admin:password_change` | GET, POST | sign in | sign in | rules | refused | yes | yes |
| Password changed | `admin:password_change_done` | GET | sign in | sign in | rules | refused | yes | yes |
| Password changed | `admin:password_change_done` | POST | sign in | sign in | rules | refused | wrong method | wrong method |
| Search box helper | `admin:autocomplete` | GET | sign in | sign in | rules | refused | refused | refused |
| Search box helper | `admin:autocomplete` | POST | sign in | sign in | rules | refused | wrong method | wrong method |
| Admin translations | `admin:jsi18n` | GET | sign in | sign in | rules | refused | yes | yes |
| Admin translations | `admin:jsi18n` | POST | sign in | sign in | rules | refused | wrong method | wrong method |
| "View on site" | `admin:view_on_site` | GET, POST | sign in | sign in | rules | refused | yes | yes |
| Staff hub section | `admin:app_list` (hub) | GET, POST | sign in | sign in | rules | refused | yes | yes |
| Audit log section | `admin:app_list` (admin) | GET, POST | sign in | sign in | rules | refused | yes | yes |
| Permission roles section | `admin:app_list` (auth) | GET, POST | sign in | sign in | rules | refused | hidden | yes |
| Library section | `admin:app_list` (library) | GET, POST | sign in | sign in | rules | refused | hidden | yes |
| Any other admin address | `admin:catch_all` | GET, POST | sign in | sign in | rules | refused | hidden | hidden |

- "No staff status" is checked for the colleague, member, author, publisher, editor and org admin, one by one.
- The search box helper only answers the admin's own search boxes, which ask with more details.

Each admin section, for the moderator and the superuser. Everyone else is refused, as on the admin home. "Open" is the
page of one record (and, for people, the password page).

| Section | Address | List | Add | Open | History | Delete |
|---|---|---|---|---|---|---|
| Posts | `hub.post` (moderator) | yes | refused | yes | yes | yes |
| Posts | `hub.post` (superuser) | yes | yes | yes | yes | yes |
| Comments | `hub.comment` (moderator) | yes | refused | yes | yes | yes |
| Comments | `hub.comment` (superuser) | yes | yes | yes | yes | yes |
| Reports | `hub.report` (moderator) | yes | refused | yes | yes | yes |
| Reports | `hub.report` (superuser) | yes | refused | yes | yes | yes |
| Audit log | `admin.logentry` (moderator) | yes | refused | view only | yes | refused |
| Audit log | `admin.logentry` (superuser) | yes | refused | view only | yes | refused |
| People | `hub.user` (moderator) | refused | refused | refused | refused | refused |
| People | `hub.user` (superuser) | yes | yes | yes | yes | yes |
| Permission roles | `auth.group` (moderator) | refused | refused | refused | refused | refused |
| Permission roles | `auth.group` (superuser) | yes | yes | yes | yes | yes |
| Groups and units | `hub.community` (moderator) | refused | refused | refused | refused | refused |
| Groups and units | `hub.community` (superuser) | yes | yes | yes | yes | yes |
| Events | `hub.event` (moderator) | refused | refused | refused | refused | refused |
| Events | `hub.event` (superuser) | yes | yes | yes | yes | yes |
| What's new | `hub.featurenote` (moderator) | refused | refused | refused | refused | refused |
| What's new | `hub.featurenote` (superuser) | yes | yes | yes | yes | yes |
| Categories | `library.category` (moderator) | refused | refused | refused | refused | refused |
| Categories | `library.category` (superuser) | yes | yes | yes | yes | yes |
| Featured links | `library.featuredlink` (moderator) | refused | refused | refused | refused | refused |
| Featured links | `library.featuredlink` (superuser) | yes | yes | yes | yes | yes |
| Articles | `library.article` (moderator) | refused | refused | refused | refused | refused |
| Articles | `library.article` (superuser) | yes | yes | yes | yes | yes |

- Reports only come from staff using the Report links, so nobody adds one here. The audit log can't be changed or deleted,
  even by a superuser.

## What the matrix found, and what changed

Fixed:

1. **The admin sent signed-in staff round in circles.** Anyone signed in without staff status who opened an admin address
   went to the admin sign-in, then the hub's sign-in, which sent them back, for ever (the browser gives up with "too many
   redirects"). They are now refused straight away (`config/urls.py`).
2. **A private group's page showed its posts to org admins who aren't in it**, while the posts themselves answered "not
   found" to them, with broken photos. The page now lists only posts the person may open (`hub/views.py`, the group page).
3. **The must-read readers list answered "refused" instead of "not found"** to people the news wasn't sent to, and showed a
   publisher outside a private group who is in it. The security test (docs/security/PENTEST-REPORT.md) found and fixed
   this first; the same two lines are here so this table holds on its own (`hub/news.py`).

Checked and left as they are:

- **Deleting someone else's post, comment or event** answers "refused" even to people who can't see it. That only shows the
  number is in use, which is no secret as numbers are counted up, and nothing about the item is shown.
- **A new starter's browser can't fetch the push script** until they accept the house rules. Harmless: push can't be
  switched on before then anyway.
- **Moderators can delete posts and comments for good in the admin**, because README.md gives them the delete right. The
  hub's own Delete keeps items for 30 days in case HR needs them; the admin's doesn't. To keep everything for 30 days, untick
  "Can delete post" and "Can delete comment" for Moderators and use "Hide" instead.

## Changing who can do what

1. Change the row here.
2. Change the code.
3. Run `python manage.py test hub.tests_access_matrix`. It lists every answer that differs from this document.

A new page fails the test until it has a row in the right section here, and in "Before signing in" too if it opens without
signing in or before the house rules. A new upload folder needs a `media` row, and a new admin section two rows.
