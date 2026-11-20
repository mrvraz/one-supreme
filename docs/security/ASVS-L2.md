# Security baseline: OWASP ASVS 4.0.3 Level 2

| | |
|---|---|
| Baseline | OWASP Application Security Verification Standard 4.0.3, Level 2. Level 2 because the hub holds staff personal data, private messages and HR evidence. |
| Version checked | `main` at 217d0bb (20 Nov 2026) plus the fixes on `team/threatmodel` |
| Checked | 20 Nov 2026, by reading every view, setting and deploy file, and running the tests named below |
| Goes with | `docs/security/THREAT-MODEL.md` (what we protect and from whom) and `docs/security/PENTEST-REPORT.md` (team/redteam's security test) |

Every Level 1 and Level 2 requirement is here. Level 3-only and deleted requirements are left out. The wording is
short; the standard has the full text.

What the status means:

| Status | Meaning |
|---|---|
| Met | The code on this branch does it. The proof is a file, a test, or both. |
| Fixed here | Not met on `main`; fixed on this branch, with a test in `hub/tests_asvs.py`. Counts as met. |
| In flight | Not met on `main`; done on another team's branch, which is waiting to be merged. Counts as met once merged. |
| Supreme | Done by Supreme IT outside the code (TLS at the proxy, MFA in Entra, disk encryption). The proof is checked at go-live. |
| Partly | Some of it is done. The rest has an owner, or is accepted with the reason given. |
| Not met | Not done. An owner is named, or it is accepted with the reason given. |
| N/A | Doesn't apply to the hub, for the reason given. |

A test name alone is in the file named next to it, or in the same file as the last one named. Team branches are
written `team/<name>`.

**Staff have no password in the hub.** They sign in with their Microsoft account; Entra ID checks the password and
the MFA. The only password account is the break-glass admin, which works only while `ALLOW_PASSWORD_LOGIN=1`. So the
password rows in V2 are about that one account, and the rows about one-time codes, recovery and authenticator apps
are Entra's.

## Summary

| Status | Requirements |
|---|---|
| Met | 142 |
| Fixed here | 10 |
| In flight | 18 |
| Supreme | 13 |
| Partly | 23 |
| Not met | 10 |
| N/A | 42 |
| **Total** | **258** |

So 152 are met on this branch, 170 once the other teams' branches are merged, and 183 once Supreme IT's go-live
checks are done. The other 33 are partly met or not met, and 42 don't apply.

Every "Partly" and "Not met" is in the table at the end, with who fixes it or why it is accepted.

## V1 Architecture, design and threat modelling

| # | Requirement | L | Status | Proof, reason or owner |
|---|---|---|---|---|
| 1.1.1 | A secure development lifecycle covers every stage | 2 | In flight | Rules for every app (`docs/FEATURE-PLAN.md` section 2), tests on every change, this baseline and the threat model. Required CI checks, CodeQL, Dependabot and `SECURITY.md`: team/foundations. |
| 1.1.2 | Threat modelling for every design change | 2 | Met | `docs/security/THREAT-MODEL.md`, section 9 says when it is redone. |
| 1.1.3 | User stories carry security constraints | 2 | Met | Abuse cases next to each story: THREAT-MODEL.md section 7. |
| 1.1.4 | Trust boundaries, components and data flows documented | 2 | Met | THREAT-MODEL.md section 4. |
| 1.1.5 | High-level architecture and every remote service analysed | 2 | Met | THREAT-MODEL.md sections 4 and 5 (Entra, Graph, push services, SMTP, LibreTranslate, SIEM, backups). |
| 1.1.6 | Central, reusable security controls | 2 | Met | `hub/security.py` (audit log, limits, headers, house rules), `hub/richtext.py`, `hub/media.py process_upload`, `library/files.py check_document`, `plugins.MEDIA_GUARDS`, Django's `LoginRequiredMiddleware`. |
| 1.1.7 | A secure coding checklist for developers and testers | 2 | Met | `docs/FEATURE-PLAN.md` "Rules for every app"; this file. |
| 1.2.1 | Low-privilege operating system accounts for every component | 2 | Met | `Dockerfile`: the app and scheduler run as user `app` (uid 1000); the Fly stage drops to it with `setpriv`. nginx and Postgres use their images' own users. |
| 1.2.2 | Components authenticate to each other, with least privilege | 2 | In flight | App to Postgres signs in with a password. On `main` it uses the owner account; the read-and-write-only `hub_app` account is team/hardening (`deploy/postgres/10-roles.sh`). nginx to app is on the private Docker network only. |
| 1.2.3 | One vetted sign-in mechanism, able to take strong authentication, with logging | 2 | Met | mozilla-django-oidc against Entra ID with PKCE and RS256 (`config/settings.py`); MFA in Entra; sign-in events logged: `test_sign_in_events_are_logged_as_json` (hub/tests.py). |
| 1.2.4 | No weaker sign-in path | 2 | Partly | The admin sends people to the one sign-in page: `test_admin_login_goes_to_the_single_sign_in_page`. The break-glass password has no MFA; it is off by default (`test_password_sign_in_can_be_switched_off`) and limited per name (team/hardening). Accepted for emergencies; team/handover's RUNBOOK says when to switch it on and off. |
| 1.4.1 | Access control enforced on the server | 2 | Met | Every check is in views and models; nothing relies on the page script. `LoginRequiredMiddleware` in `config/settings.py`. |
| 1.4.4 | One access control mechanism that every request passes | 2 | Met | Django permissions plus the model rules (`Post.objects.viewable_by`, `Community.can_view` and `is_admin`, `chat/views.py member_or_404`). Every uploaded file goes through `hub/views.py media` and its guard. |
| 1.4.5 | Access checked per feature and per item, roles grant permissions | 2 | Met | Per-item checks above; roles are Django groups (README "Roles"). |
| 1.5.1 | Input and output rules by data type, content and law | 2 | Met | FEATURE-PLAN rules 3 and 4 (formatted text, uploads); data classes in THREAT-MODEL.md section 2. Data protection rules: team/compliance `docs/compliance/`. |
| 1.5.2 | No serialised objects from untrusted clients | 2 | Met | Only forms and JSON (`json.loads`); sessions are stored in the database, not in signed cookies. |
| 1.5.3 | Input validated on a trusted layer | 2 | Met | Django forms and checks in the views. |
| 1.5.4 | Output encoded close to its interpreter | 2 | Met | Template auto-escaping; `hub/richtext.py` escapes then adds tags; `JsonResponse`; calendar text escaped in `hub/views.py _ics_text`. |
| 1.6.1 | A key management policy and lifecycle | 2 | In flight | Every key and when to rotate it: team/handover `docs/operations/RUNBOOK.md` "Rotating keys". |
| 1.6.2 | Secrets kept in a vault or behind an API | 2 | Not met | Secrets sit in `.env` on the one server, readable by one account. Accepted (THREAT-MODEL.md K7). |
| 1.6.3 | Keys and passwords can be replaced | 2 | In flight | All come from `.env`; how to replace each without losing data: team/handover RUNBOOK.md "Rotating keys". |
| 1.6.4 | No secrets on the client used to protect data | 2 | Met | The browser holds only the session cookie, the form token and the public push key. |
| 1.7.1 | One logging format across the system | 2 | Met | Security events are JSON lines from `hub.security.JsonFormatter`; nginx and gunicorn keep their usual formats. |
| 1.7.2 | Logs sent to a remote system for analysis | 2 | Supreme | The JSON lines go to Docker's log; Supreme's SIEM collects them (README "Security notes"; team/reliability MONITORING.md). |
| 1.8.1 | Sensitive data identified and classed | 2 | Met | THREAT-MODEL.md section 2; data inventory in team/compliance. |
| 1.8.2 | Each class has protection rules that are applied | 2 | Met | THREAT-MODEL.md section 2, "How it is protected"; retention in `hub/management/commands/purge.py`. |
| 1.9.1 | Traffic between components encrypted | 2 | Partly | Browser to proxy: TLS (Supreme). Microsoft, push, SMTP with `EMAIL_USE_TLS=1`: TLS. Proxy to nginx and inside Docker: plain. Accepted (THREAT-MODEL.md K8). |
| 1.9.2 | Each side checks the other's certificate | 2 | Met | `requests` checks certificates by default (`hub/push.py`, `hub/views.py translate`, `sync_directory`, mozilla-django-oidc); Django's SMTP uses a verifying TLS context. |
| 1.10.1 | Source control with traceable, reviewed changes | 2 | In flight | Git. Protected `main`, pull requests and required checks: team/foundations `docs/operations/GITHUB-SETUP.md`. |
| 1.11.1 | Every component documented by what it does | 2 | Met | README "Code map"; THREAT-MODEL.md section 4. |
| 1.11.2 | High-value flows share no unsynchronised state | 2 | Met | All state is in Postgres; gunicorn workers share nothing in memory. Limit counters in the database cache: team/hardening. |
| 1.12.2 | Uploaded files download, or come from another domain, with a CSP | 2 | Partly | Anything not a picture, video or sound downloads (`hub/views.py media`); pictures are re-made so carry no script. Files nginx sends don't get the CSP (RT-12): team/hardening. |
| 1.14.1 | Components of different trust kept apart | 2 | Met | Only nginx has a port (`docker-compose.yml`); database and app are internal; `/admin/` by address range (team/hardening); firewall (Supreme). |
| 1.14.2 | Signed binaries to remote devices | 2 | N/A | Nothing is installed on devices; it's a web app. |
| 1.14.3 | The build warns of old or vulnerable parts | 2 | In flight | pip-audit and Dependabot in CI: team/foundations. |
| 1.14.4 | The build checks a secure deployment | 2 | In flight | CI runs the deploy check with production settings and builds the image: team/foundations. |
| 1.14.5 | Deployments sandboxed, in containers, isolated | 2 | Met | Docker containers on a private network (`docker-compose.yml`); ffmpeg runs as a separate process with a timeout (`hub/media.py strip_video`). |
| 1.14.6 | No deprecated client technology | 2 | Met | Plain HTML, CSS and JavaScript. |

## V2 Authentication

| # | Requirement | L | Status | Proof, reason or owner |
|---|---|---|---|---|
| 2.1.1 | Passwords at least 12 characters | 1 | Fixed here | `config/settings.py` `MinimumLengthValidator` with `min_length` 12; `test_2_1_1_passwords_need_at_least_12_characters` (hub/tests_asvs.py). |
| 2.1.2 | 64-character passwords allowed; over 128 refused | 1 | Partly | Any length is allowed and hashed whole. Not refused over 128. Accepted: one break-glass account, PBKDF2 doesn't truncate. |
| 2.1.3 | No truncation | 1 | Met | Django's PBKDF2 hashes the whole password. |
| 2.1.4 | Any printable Unicode allowed | 1 | Met | Django accepts every character. |
| 2.1.5 | Users can change their password | 1 | Met | Django admin "Change password" for the break-glass admin. Staff: in Microsoft. |
| 2.1.6 | Change needs the current and the new password | 1 | Met | Django's `PasswordChangeForm`. |
| 2.1.7 | Passwords checked against breached or common ones | 1 | Met | `CommonPasswordValidator` (20,000 common passwords) in `config/settings.py`. Staff passwords are Entra's. |
| 2.1.8 | A password strength meter | 1 | Not met | Accepted: one break-glass account, set by IT with the 12-character and common-password checks. |
| 2.1.9 | No composition rules | 1 | Met | Only length, similarity and common-password checks. |
| 2.1.10 | No forced rotation or history | 1 | Met | None in the hub. RUNBOOK changes the break-glass password after each use (team/handover), which is not periodic. |
| 2.1.11 | Paste and password managers allowed | 1 | Met | Plain inputs, nothing blocks paste (`hub/templates/hub/login.html`). |
| 2.1.12 | A way to show the typed password | 1 | Not met | Accepted: one break-glass account, typed by IT. Some browsers add their own reveal button. |
| 2.2.1 | Defences against credential stuffing and brute force | 1 | Met | nginx: 10 password tries a minute per address (`deploy/nginx.conf`); 10 per name per 15 minutes (team/hardening `test_password_guessing_is_stopped_per_sign_in_name`); Entra smart lockout for staff (Supreme). |
| 2.2.2 | SMS and email only as a second step | 1 | Supreme | The hub has no SMS or email sign-in. Entra's methods: team/handover ENTRA-SETUP.md step 7. |
| 2.2.3 | People told about changes to their sign-in details | 1 | N/A | The hub holds no staff credentials; Microsoft tells people. |
| 2.3.1 | Generated first passwords random, at least 6 characters, short-lived | 1 | N/A | Production generates none. Demo servers only: `demo_logins` makes a 16-character random one. |
| 2.3.2 | Security keys (FIDO) can be enrolled and used | 2 | Supreme | Entra passkeys and security keys; ENTRA-SETUP.md step 7 recommends phishing-resistant MFA (team/handover). |
| 2.3.3 | Renewal reminders for time-bound authenticators | 2 | In flight | The Entra app's certificate: team/handover alerts before it expires and when it is refused (`test_a_refused_certificate_emails_microsofts_reason`). |
| 2.4.1 | Passwords stored with an approved password hash | 2 | Met | Django PBKDF2-SHA256 (default `PASSWORD_HASHERS`). |
| 2.4.2 | Salt at least 32 bits | 2 | Met | Django's salt is 22 random characters (about 128 bits). |
| 2.4.3 | PBKDF2 at least 100,000 iterations | 2 | Met | Django 5.2 uses 1,000,000. |
| 2.4.4 | bcrypt work factor at least 10 | 2 | N/A | bcrypt isn't used. |
| 2.4.5 | An extra secret salt (pepper) | 2 | Not met | Django has none. Accepted: one break-glass account. |
| 2.5.1 | First or recovery secrets not sent in clear text | 1 | N/A | The hub sends none; staff recovery is Entra's. |
| 2.5.2 | No password hints or secret questions | 1 | Met | None. |
| 2.5.3 | Recovery never shows the current password | 1 | N/A | No recovery in the hub. The break-glass password is reset by `manage.py changepassword` (team/handover RUNBOOK.md). |
| 2.5.4 | No shared or default accounts such as "admin" | 1 | Partly | No default accounts: the break-glass admin is made at install. It is shared by IT by nature; RUNBOOK.md (team/handover) names it, keeps its email outside the company domains and changes its password after every use. |
| 2.5.5 | People told when a sign-in factor changes | 1 | N/A | Entra's. |
| 2.5.6 | Recovery through a secure route | 1 | N/A | Entra self-service reset (Supreme). |
| 2.5.7 | Lost MFA needs the same identity proof as enrolment | 2 | Supreme | Supreme's IT service desk process for Entra. |
| 2.6.1 | Look-up secrets used once | 2 | N/A | The hub has none. |
| 2.6.2 | Look-up secrets random enough | 2 | N/A | The hub has none. |
| 2.6.3 | Look-up secrets resist offline attack | 2 | N/A | The hub has none. |
| 2.7.1 | No SMS or phone codes by default | 1 | Supreme | Entra methods: ENTRA-SETUP.md step 7 (team/handover). |
| 2.7.2 | Out-of-band codes expire in 10 minutes | 1 | N/A | Entra's. |
| 2.7.3 | Out-of-band codes used once, for one request | 1 | N/A | Entra's. |
| 2.7.4 | Out-of-band channel secure and separate | 1 | N/A | Entra's. |
| 2.7.5 | Only a hash of the code kept | 2 | N/A | Entra's. |
| 2.7.6 | Codes from a secure random generator | 2 | N/A | Entra's. |
| 2.8.1 | Time-based codes have a lifetime | 1 | N/A | Entra's (Authenticator app). |
| 2.8.2 | Code-checking keys well protected | 2 | N/A | Entra's. |
| 2.8.3 | Approved algorithms for one-time codes | 2 | N/A | Entra's. |
| 2.8.4 | A time-based code works once | 2 | N/A | Entra's. |
| 2.8.5 | A reused code is logged, refused and reported | 2 | N/A | Entra's. |
| 2.8.6 | A lost code device can be revoked at once | 2 | N/A | Entra's; IT then revokes sessions, which the hub follows within 15 minutes. |
| 2.9.1 | Verification keys kept in secure storage | 2 | N/A | No cryptographic authenticators in the hub. |
| 2.9.2 | Challenge nonce at least 64 bits | 2 | N/A | As above. |
| 2.9.3 | Approved algorithms for cryptographic verifiers | 2 | N/A | As above. |
| 2.10.1 | Service secrets aren't unchanging passwords or keys | 2 | Partly | The Entra app uses a certificate, not a secret (team/handover). The database passwords and the push key are fixed until rotated by the runbook. Accepted for one on-premises server. |
| 2.10.2 | Service accounts don't use default passwords | 2 | Met | `docker-compose.yml` refuses to start without `DB_PASSWORD`; the Postgres superuser loses its network sign-in (team/hardening). |
| 2.10.3 | Service passwords resist offline recovery, even locally | 2 | Not met | They are in `.env`, readable by one account (`chmod 600`, README "Before go-live"). Accepted (THREAT-MODEL.md K7). |
| 2.10.4 | Secrets not in the source code or repository | 2 | Met | All from the environment (`config/settings.py`); `.env` in `.gitignore` and `.dockerignore`; gitleaks in CI (team/foundations). The only password in the code is the local demo one in `seed_demo.py`, which doesn't work on a server. |

## V3 Session management

| # | Requirement | L | Status | Proof, reason or owner |
|---|---|---|---|---|
| 3.1.1 | No session tokens in addresses | 1 | Met | Cookie only. The one-time sign-in code in `/oidc/callback/` isn't a session, and nginx logs drop query strings (team/hardening). |
| 3.2.1 | A new session at sign-in | 1 | Met | Django's `login()` makes a new session key; `test_signing_in_gives_a_new_session_and_signing_out_ends_it` (team/redteam). |
| 3.2.2 | Session tokens at least 64 bits | 1 | Met | Django session keys: 32 random characters (about 165 bits). |
| 3.2.3 | Tokens kept only in secure cookies | 1 | Met | Database sessions with an HttpOnly cookie; nothing in browser storage. |
| 3.2.4 | Tokens made with approved algorithms | 2 | Met | Django uses Python's `secrets`. |
| 3.3.1 | Sign-out and expiry end the session, Back can't resume it, nor another site of the same sign-in | 1 | Fixed here | The session is deleted; signed-in pages are sent `no-store`; Sign out also signs the browser out of Entra (`hub/auth.py provider_logout_url`, `hub/urls.py`). `test_3_3_1_signing_out_also_signs_the_browser_out_of_microsoft`, `test_8_2_1_...` (hub/tests_asvs.py). Microsoft only sends people back to the hub if `/login/` is a redirect URI on the app: team/handover adds it to ENTRA-SETUP.md. |
| 3.3.2 | Level 2: sign in again after 12 hours, or 30 minutes idle | 1 | In flight | Sessions last 12 hours (team/hardening `SESSION_COOKIE_AGE`). On `main`, password sessions last two weeks (RT-13). Single sign-on is also checked with Entra every 15 minutes. |
| 3.3.3 | Other sessions can be ended after a password change | 2 | Met | Django ends the other sessions of a password account when its password changes. Staff: IT revokes sessions in Entra; the hub follows within 15 minutes. |
| 3.3.4 | People can see and end their own sessions on other devices | 2 | Not met | Accepted for go-live (THREAT-MODEL.md K6): IT revokes Entra sessions, or switches the account off in the hub, which takes effect on the next request (`hub/auth.py get_user`). A "your devices" page later: team/hardening. |
| 3.4.1 | Session cookie Secure | 1 | Met | `SESSION_COOKIE_SECURE = not DEBUG` (`config/settings.py`). |
| 3.4.2 | Session cookie HttpOnly | 1 | Met | Django's default. |
| 3.4.3 | Session cookie SameSite | 1 | Met | Django's default, Lax (Strict would drop the session on the way back from Microsoft). |
| 3.4.4 | Session cookie uses the `__Host-` prefix | 1 | Fixed here | `SESSION_COOKIE_NAME = "__Host-sessionid"` when `DEBUG` is off (`config/settings.py`); `test_3_4_4_production_session_cookie_is_host_only_and_single_sign_on_signs_out_of_microsoft`. |
| 3.4.5 | Narrowest cookie path when sharing a domain | 1 | N/A | The hub has its own host name, and `__Host-` requires path `/`. |
| 3.5.1 | People can revoke tokens given to linked apps | 2 | N/A | No other apps get access through the hub. |
| 3.5.2 | Session tokens, not fixed API keys | 2 | Met | Browsers use the session; there are no user API keys. |
| 3.5.3 | Stateless tokens signed and protected | 2 | N/A | Sessions are stored in the database. Microsoft's ID tokens are checked with RS256 against its keys (`OIDC_RP_SIGN_ALGO`). |
| 3.7.1 | A full session, or signing in again, before sensitive changes | 1 | Met | Every action needs a full session; there are no half-signed-in states. The admin also needs the office or VPN (team/hardening). |

## V4 Access control

| # | Requirement | L | Status | Proof, reason or owner |
|---|---|---|---|---|
| 4.1.1 | Rules enforced on the server | 1 | Met | See 1.4.1. `test_everything_needs_sign_in` (hub/tests.py); `test_every_page_needs_sign_in_except_the_public_few` (team/redteam). |
| 4.1.2 | Users can't change the data access rules use | 1 | Met | Every form lists its fields (`hub/forms.py`); `sso_id` and permissions only in the admin; `test_extra_form_fields_cannot_make_someone_an_admin_or_change_who_they_are` (team/redteam). |
| 4.1.3 | Least privilege | 1 | Met | Roles in README "Roles"; per-item checks; `test_usage_figures_need_permission`, `test_only_publishers_write_news` (hub/tests_features.py). |
| 4.1.5 | Fails safe, also on errors | 1 | Met | File guards say no by default and folders without a guard are never served (`hub/views.py media`); an error gives a plain 500 page. |
| 4.2.1 | No insecure direct object references | 1 | Met | `test_group_posts_only_reach_members_feeds`, `test_photos_of_hidden_or_deleted_posts_are_blocked_except_for_moderators` (hub/tests.py); `test_only_members_can_read_poll_send_or_open_pictures` (chat/tests.py); `test_private_group_files_download_for_members_only_under_their_original_name` (library/tests.py); `test_people_without_the_journey_get_404` (journeys/tests.py); `test_who_is_interested_is_private` (jobs/tests.py); team/redteam's sweeps. |
| 4.2.2 | Strong CSRF protection | 1 | Met | `CsrfViewMiddleware`; every change is a POST; `test_writes_must_be_posts` (chat/tests.py); `test_every_post_needs_a_csrf_token` (team/redteam). |
| 4.3.1 | Admin pages need MFA | 1 | Partly | The admin only takes single sign-on (`test_admin_login_goes_to_the_single_sign_in_page`), and Entra requires MFA (Supreme; team/handover ENTRA-SETUP.md step 7). The break-glass password has no MFA: see 1.2.4. |
| 4.3.2 | No directory listings or metadata files | 1 | Met | nginx has no `autoindex`; files only through the app's guard; `.git` stays out of the image (`.dockerignore`). |
| 4.3.3 | Step-up or separation of duties for high-value actions | 2 | Partly | Duties are split into roles (README "Roles"); no step-up sign-in. Accepted: no money moves, and the admin needs MFA and the office network (team/hardening). |

## V5 Validation, sanitisation and encoding

| # | Requirement | L | Status | Proof, reason or owner |
|---|---|---|---|---|
| 5.1.1 | Defences against parameter pollution | 1 | Met | Views read one value per name; ids are checked (`as_id`, `isdecimal`); `test_ids_that_are_not_numbers_are_ignored_not_crashed_on` (hub/tests_features.py). |
| 5.1.2 | No mass assignment | 1 | Met | Model forms list their fields (`hub/forms.py`, `*/forms.py`). |
| 5.1.3 | All input validated against an allow list | 1 | Met | Typed form fields, fixed choices, numeric ids; the translation language from a fixed list (team/redteam `test_the_translation_language_is_one_from_the_list`). |
| 5.1.4 | Structured data typed and checked | 1 | Met | Forms; the push sign-up checks keys, types and lengths (`hub/account.py push_subscribe`). |
| 5.1.5 | Redirects only to allowed places | 1 | Met | `hub/views.py safe_redirect` (`url_has_allowed_host_and_scheme`); the sign-out redirect is fixed. `test_redirects_never_leave_the_site` (team/redteam). |
| 5.2.1 | HTML input sanitised | 1 | Met | No HTML is accepted; the light formatting is escaped first (`hub/richtext.py`). |
| 5.2.2 | Free text checked for characters and length | 1 | Partly | Every field has a maximum length. A NUL character in a search box reaches Postgres and gives an error page (RT-10): team/hardening. |
| 5.2.3 | No mail header injection | 1 | Met | Fixed subjects; Django refuses line breaks in headers; the digest is plain text. |
| 5.2.4 | No `eval` or dynamic code | 1 | Met | None in Python or JavaScript; the CSP has no `unsafe-eval`. |
| 5.2.5 | No template injection | 1 | Met | Templates are files; user text is never compiled as a template. |
| 5.2.6 | No SSRF | 1 | Met | Push only to known services (`hub/account.py PUSH_HOSTS`; `test_push_only_accepts_known_push_services`); translation only to `TRANSLATE_URL`. The `\@` trick that got past the host check is fixed on team/redteam (RT-01). |
| 5.2.7 | SVG can't run script | 1 | Met | SVG uploads are refused; `hub/views.py media` never shows SVG inline. |
| 5.2.8 | Markdown and similar can't run script | 1 | Met | `hub/richtext.py`: escape first; links http(s) only. |
| 5.3.1 | Output encoding fits the context | 1 | Met | HTML auto-escaping, JSON, calendar escaping, `content_disposition_header`. |
| 5.3.2 | Encoding keeps the character set | 1 | Met | UTF-8 throughout. |
| 5.3.3 | Protection against reflected, stored and DOM XSS | 1 | Met | Auto-escaping, `hub/richtext.py`, CSP `script-src 'self'`; `test_messages_are_escaped_and_formatted` (chat/tests.py); `test_the_description_is_formatted_and_never_trusted` (jobs/tests.py); `test_translation_is_escaped_and_uses_the_readers_language`; `test_typed_html_never_reaches_a_page_as_html` (team/redteam). |
| 5.3.4 | Parameterised queries | 1 | Met | Django's ORM only; no raw SQL. |
| 5.3.5 | Context encoding where no safer API exists | 1 | Met | Calendar files (`_ics_text`), download names (`library/files.py download_name`). |
| 5.3.6 | No JSON injection or eval | 1 | Met | `JsonResponse` on the server, `response.json()` in `app.js`. |
| 5.3.7 | No LDAP injection | 1 | N/A | No LDAP. |
| 5.3.8 | No OS command injection | 1 | Met | ffmpeg gets a list of arguments, no shell, and fixed file names (`hub/media.py strip_video`). |
| 5.3.9 | No local or remote file inclusion | 1 | Met | `safe_join` and the real-path guard in `hub/views.py media`; `test_media_is_served_only_inside_the_media_folder`. |
| 5.3.10 | No XPath or XML injection | 1 | N/A | No XML is processed. |
| 5.4.1 | Memory-safe code | 2 | Met | Python. Pillow and ffmpeg are native: pixel limits, timeouts and patching (README "Before go-live"). |
| 5.4.2 | Format strings fixed | 2 | Met | Log events are fixed names (`hub/security.py audit`); no user text as a format string. |
| 5.4.3 | No integer overflows | 2 | Met | Python integers; ids too big for the database are "not found" (`test_ids_that_are_not_numbers_are_ignored_not_crashed_on`; team/redteam RT-08). |
| 5.5.1 | Serialised objects checked or encrypted | 1 | Met | None come from clients; sessions are in the database. |
| 5.5.2 | XML parsers can't read outside entities | 1 | N/A | No XML parsing; Office files are stored, not opened. |
| 5.5.3 | No unsafe deserialisation | 1 | Met | Only `json.loads`. |
| 5.5.4 | `JSON.parse`, not `eval`, in the browser | 1 | Met | `app.js` uses `fetch(...).json()`. |

## V6 Stored cryptography

| # | Requirement | L | Status | Proof, reason or owner |
|---|---|---|---|---|
| 6.1.1 | Personal data encrypted at rest | 2 | Supreme | Encrypted server disks (README "Before go-live", Supreme IT); encrypted backups (team/reliability). |
| 6.1.2 | Health data encrypted at rest | 2 | N/A | The hub asks for no health data. What staff choose to post falls under 6.1.1. |
| 6.1.3 | Financial data encrypted at rest | 2 | N/A | No financial data. Salaries in vacancies aren't personal. |
| 6.2.1 | Crypto fails safely, no padding oracles | 1 | Met | Only vetted libraries: Django, `cryptography`, `http_ece`, `py_vapid`. |
| 6.2.2 | Proven algorithms and libraries | 2 | Met | As above; push uses RFC 8291 (`hub/push.py`); PBKDF2 and HMAC-SHA256 in Django. |
| 6.2.3 | Modes and IVs set up securely | 2 | Met | `aes128gcm` with a random salt and a new key per message (`hub/push.py send_to`). |
| 6.2.4 | Algorithms can be swapped | 2 | Met | Django's hashers can be upgraded in settings; algorithms live in the libraries. |
| 6.2.5 | No ECB, PKCS#1 v1.5, small-block ciphers, MD5 or SHA-1 | 2 | Met | None in the app code. |
| 6.2.6 | Nonces never reused | 2 | Met | `os.urandom(16)` salt and a fresh key for every push (`hub/push.py`). |
| 6.3.1 | Secure random numbers for unguessable values | 2 | Met | `uuid4` file names, Django's `secrets`-based tokens, `secrets.token_urlsafe` in `demo_logins`. |
| 6.3.2 | GUIDs are v4 from a secure generator | 2 | Met | `uuid.uuid4()` (from `os.urandom`) in `hub/media.py` and `library/files.py`. |
| 6.4.1 | A secrets manager | 2 | Not met | `.env` on the server. Accepted (THREAT-MODEL.md K7). |
| 6.4.2 | Keys kept in a separate security module | 2 | Not met | The push key and the Entra certificate key are files the app reads. Accepted (K7). |

## V7 Errors and logging

| # | Requirement | L | Status | Proof, reason or owner |
|---|---|---|---|---|
| 7.1.1 | No passwords or payment details in logs; session ids only hashed | 1 | In flight | The app logs no passwords (`sign_in_failed` logs the name only). Blanking of secrets, codes and session ids in every line, and nginx logs without query strings: team/hardening `test_secrets_are_blanked_out_of_every_log_line`. |
| 7.1.2 | No other sensitive data in logs | 1 | Met | Events carry email, user id, address and path, which investigations need, never post or chat text; crash emails are off (`test_crashes_are_logged_not_emailed`). |
| 7.1.3 | Security events logged: sign-ins, failures, access refusals, bad input | 2 | Partly | Sign-ins and failures, refusals by Microsoft or the domain list, limits hit, deletions, moderation, exports, and every 403 (`hub/security.py log_refusals`, this branch). Form mistakes aren't logged: they are ordinary typing errors, and logging them would bury the real events. |
| 7.1.4 | Log events allow a timeline | 2 | Met | Time with offset, level, event, user, user id, address, path (`hub/security.py JsonFormatter`). |
| 7.2.1 | Every authentication decision logged, without tokens | 2 | Met | `sign_in`, `sign_out`, `sign_in_failed`, `sign_in_rejected` (`hub/security.py`, `hub/auth.py`); `test_sign_in_events_are_logged_as_json`, `test_sso_only_lets_in_company_addresses_logs_refusals_and_syncs_names`. |
| 7.2.2 | Access decisions can be logged, every refusal is | 2 | Fixed here | Every 403 (no permission, or no valid form token) is logged as `access_denied` with who, where and how (`hub/security.py log_refusals`, last in `MIDDLEWARE`); `test_7_2_2_refused_requests_are_logged_with_who_and_where`. Admin refusals by address: `admin_blocked` (team/hardening). Things a person may not see answer "not found" and aren't logged, as they look like any mistyped link. |
| 7.3.1 | Log injection prevented | 2 | Met | JSON lines escape line breaks; Django 5.2.19 escapes control characters in logged paths. |
| 7.3.3 | Security logs protected from reading and change | 2 | Supreme | Docker logs readable by server admins only; the SIEM keeps its own copy (Supreme). The admin's log is read-only (`hub/admin.py AuditLogAdmin`). |
| 7.3.4 | Clocks synchronised; UTC | 2 | Supreme | The server keeps time by NTP (Supreme). Times are stored in UTC (`USE_TZ`) and logged with their offset. |
| 7.4.1 | A plain error message, without details | 1 | Met | `DEBUG` off by default; Django's plain 500 page. Friendly error pages: team/experience; `test_errors_show_no_details` (team/redteam). |
| 7.4.2 | Errors handled across the code | 2 | Met | Upload, push, translation and leaver-check errors are caught and explained (`hub/media.py`, `hub/push.py`, `hub/views.py translate`, `sync_directory`). |
| 7.4.3 | A last-resort error handler | 2 | Met | Django's handler logs every crash (`test_crashes_are_logged_not_emailed`); the scheduler catches and logs each job (`hub/management/commands/scheduler.py run`). |

## V8 Data protection

| # | Requirement | L | Status | Proof, reason or owner |
|---|---|---|---|---|
| 8.1.1 | Sensitive data not cached by proxies or app caches | 2 | Met | nginx has no proxy cache; no CDN. Pages and data answers are `private, no-store` (this branch). |
| 8.1.2 | Temporary copies protected or removed | 2 | Met | The data export zip is a temporary file removed when sent (`hub/account.py export_my_data`); video work folders are removed (`hub/media.py strip_video`). |
| 8.1.3 | Few parameters in requests | 2 | Met | Forms carry only what they need; no hidden field grants anything (FEATURE-PLAN rule 2). |
| 8.1.4 | Abnormal numbers of requests detected and alerted | 2 | Partly | nginx returns 429 on floods; `rate_limited` and `access_denied` events go to the SIEM. The alert rules are Supreme's SIEM: team/reliability adds them to MONITORING.md. |
| 8.2.1 | Anti-caching headers on sensitive pages | 1 | Fixed here | Every signed-in answer without its own caching rule is `private, no-store` (`hub/security.py security_headers`); `test_8_2_1_signed_in_pages_are_never_kept_by_the_browser_and_14_4_2_json_downloads`. Photos and videos stay private-cached for a day (THREAT-MODEL.md K4). |
| 8.2.2 | No sensitive data in browser storage | 1 | Met | The scripts use no local or session storage; the push worker keeps no pages. |
| 8.2.3 | Signed-in data cleared from the browser after sign-out | 1 | Fixed here | Nothing signed-in is stored (8.2.1), and Sign out ends the Microsoft session too (3.3.1). Same tests. |
| 8.3.1 | Sensitive data in the body or headers, not the address | 1 | Met | Forms are POSTed. Search words are in the address, as searches are; nginx logs drop query strings (team/hardening). |
| 8.3.2 | People can export or remove their data | 1 | Met | "Download my data" (`test_people_can_download_their_data`); people delete their own posts, comments and messages; leavers' accounts go after `LEAVER_RETENTION_DAYS`. |
| 8.3.3 | Clear words about what is collected, accepted before use | 1 | Met | House rules with a data notice, accepted at first sign-in (`test_newcomers_accept_the_house_rules_first_and_again_when_they_change`). The privacy notice page: team/compliance. |
| 8.3.4 | All sensitive data identified, with a policy | 1 | Met | THREAT-MODEL.md section 2; team/compliance data inventory and retention. |
| 8.3.5 | Access to sensitive data audited | 2 | Partly | Exports, moderation actions, deletions and report handling are logged. A moderator only opening a hidden post or a chat picture in the admin isn't. team/compliance decides in the DPIA whether it must be; team/hardening adds it if so. |
| 8.3.6 | Sensitive data wiped from memory after use | 2 | N/A | Python can't reliably wipe memory; nothing sensitive is held longer than a request. |
| 8.3.7 | Encryption gives secrecy and integrity | 2 | Met | TLS (Supreme), push `aes128gcm`, backups encrypted (team/reliability). |
| 8.3.8 | Old personal data deleted on a schedule | 2 | Met | `hub/management/commands/purge.py` daily; `test_retention_removes_old_alerts_and_counts_from_the_day_someone_left`, `test_purge_keeps_alerts_at_0_keeps_reported_leavers_and_removes_covers`; chat `test_purger_removes_old_deleted_messages_and_their_pictures`. Production periods: team/compliance. |

## V9 Communication

| # | Requirement | L | Status | Proof, reason or owner |
|---|---|---|---|---|
| 9.1.1 | TLS for every client connection, no fallback | 1 | In flight | TLS at Supreme's proxy. HTTPS redirect and one-year HSTS on by default: team/hardening (`test_production_settings_pass_djangos_deploy_check`). On `main` both are off until set. |
| 9.1.2 | Only strong cipher suites | 1 | Supreme | Supreme's proxy. team/handover adds a TLS test of the live address to GO-LIVE.md (see the table at the end). |
| 9.1.3 | Only TLS 1.2 and 1.3 | 1 | Supreme | As above. |
| 9.2.1 | Trusted certificates for connections to and from the server | 2 | Met | `requests` and Django's SMTP check certificates against trusted roots. |
| 9.2.2 | TLS for every inbound and outbound connection | 2 | Partly | Outbound to Microsoft, push services and SMTP with `EMAIL_USE_TLS=1`: TLS. Proxy to nginx, the database and LibreTranslate when its address is `http`: plain, inside Supreme's network. Accepted (THREAT-MODEL.md K8); Supreme IT can add TLS. |
| 9.2.3 | Connections to outside systems authenticated | 2 | Met | Entra (certificate, team/handover), Graph (token), push (VAPID signature), SMTP (user and password), LibreTranslate (API key). |
| 9.2.4 | Certificate revocation checks (OCSP stapling) | 2 | Supreme | At Supreme's proxy. |

## V10 Malicious code

| # | Requirement | L | Status | Proof, reason or owner |
|---|---|---|---|---|
| 10.2.1 | No phone-home or hidden data collection | 2 | Met | No analytics or outside scripts (CSP `'self'`); outbound only to Entra, Graph, push services, SMTP and `TRANSLATE_URL`. |
| 10.2.2 | No needless device permissions | 2 | Met | `Permissions-Policy` denies camera, microphone, location, payment and USB (`hub/security.py`); push is asked for only when someone switches it on. |
| 10.3.1 | Auto-updates over a secure channel, signed | 1 | N/A | No auto-update; IT updates with `git pull` and a rebuild. |
| 10.3.2 | Integrity protection; no code from untrusted places | 1 | Met | Every script comes from the hub itself (CSP `script-src 'self'`); libraries pinned in `requirements.txt` from PyPI. |
| 10.3.3 | Protection against subdomain takeover | 1 | Supreme | Supreme owns the hub's DNS name. |

## V11 Business logic

| # | Requirement | L | Status | Proof, reason or owner |
|---|---|---|---|---|
| 11.1.1 | Steps in order, none skipped | 1 | Met | Journeys unlock in order (`test_steps_unlock_in_order_but_editors_can_open_any`); house rules before anything else; private groups by invitation or approved request (`test_private_groups_need_an_invitation_or_an_approved_request`). |
| 11.1.2 | Steps at human speed | 1 | Partly | Per-person limits per hour and day stop bursts; there is no "too fast" check per step. Accepted: nothing here gains from speed except floods, which the limits stop. |
| 11.1.3 | Business limits per person | 1 | Met | `hub/security.py LIMITS` plus chat, library and jobs; `test_activity_limits_stop_floods`, `test_rate_limit` (chat), `test_uploads_are_limited_per_day` (library), `test_one_person_can_show_interest_in_20_vacancies_a_day` (jobs). |
| 11.1.4 | Anti-automation against bulk copying, uploads and floods | 1 | Met | As 11.1.3, plus nginx request limits and the disk guard (`test_uploads_pause_and_admins_are_emailed_when_the_disk_fills`). Search and export limits: team/hardening. |
| 11.1.5 | Limits for the business risks in the threat model | 1 | Met | THREAT-MODEL.md sections 7 and 8: one vote, one level of replies, evidence kept, reports limited. |
| 11.1.6 | No time-of-check races in sensitive operations | 2 | Partly | One vote, one RSVP, one interest and one membership are database constraints (`hub/models.py`, `jobs/models.py`, `chat/models.py`). Activity limits count rows, so two requests at the same moment can both get in under the limit. Accepted: the limits are generous and a race lets only a few extra through. Owner of the limits: team/hardening. |
| 11.1.7 | Unusual activity monitored | 2 | Partly | `rate_limited`, `access_denied`, `sign_in_rejected` and `admin_blocked` reach the SIEM; what to watch is in team/handover RUNBOOK.md "Alerts". The SIEM rules: Supreme IT. |
| 11.1.8 | Alerts on automated attacks | 2 | Partly | As 11.1.7; team/reliability adds the SIEM alert rules to MONITORING.md. |

## V12 Files and resources

| # | Requirement | L | Status | Proof, reason or owner |
|---|---|---|---|---|
| 12.1.1 | No files big enough to fill the disk | 1 | Met | Photos 15 MB, videos 100 MB, 250 MB per post, documents 50 MB, nginx 260 MB (`hub/media.py`, `hub/forms.py`, `library/files.py`, `deploy/nginx.conf`); `test_posts_over_the_total_upload_size_are_refused_with_a_message`. |
| 12.1.2 | Archives checked before unpacking | 2 | N/A | The hub never unpacks uploads; Office files are stored as they are. Pictures that unpack huge are refused (`test_a_photo_with_too_many_pixels_is_refused_before_it_is_unpacked`). |
| 12.1.3 | A per-person quota | 2 | Met | Per person a day: 60 photos or videos in posts, 60 pictures in chat, 50 library documents (`LIMITS`, `hub/forms.py`, `chat/views.py`, `library/views.py`); uploads pause at 95% disk. |
| 12.2.1 | File type checked by content | 2 | Met | `hub/media.py process_upload`, `library/files.py check_document`; `test_files_that_are_not_photos_or_videos_are_rejected`, `test_disguised_wrong_and_oversized_files_are_refused` (library/tests.py). |
| 12.3.1 | Uploaded file names not used on disk | 1 | Met | Stored under random names (`uuid4`). |
| 12.3.2 | File names can't reach local files | 1 | Met | As 12.3.1; the original name is only a download name, cleaned (`library/files.py download_name`). |
| 12.3.3 | File names can't fetch remote files | 1 | Met | No file name is ever fetched. |
| 12.3.4 | No reflected file download | 1 | Fixed here | JSON answers download under a fixed name (`hub/security.py security_headers`); download names are built by `content_disposition_header`. `test_8_2_1_..._and_14_4_2_json_downloads`. |
| 12.3.5 | File metadata never reaches a command line | 1 | Met | ffmpeg gets fixed names in a work folder (`hub/media.py strip_video`). |
| 12.3.6 | No code from untrusted sources (CDNs, npm) | 2 | Met | No CDN, no npm; CSP `'self'`. |
| 12.4.1 | Uploads outside the web root, limited permissions | 1 | Met | In `DATA_DIR/media`, apart from the code; nginx mounts it read-only and serves it only through an `internal` location. |
| 12.4.2 | Uploads scanned for viruses | 1 | Not met | Accepted for now (THREAT-MODEL.md risk 7, K5). Supreme IT decides; team/hardening adds a scanner container if they want one. |
| 12.5.1 | The web tier serves only expected file types | 1 | Met | nginx serves nothing from disk itself; static files are only the collected ones; uploads only through the guard. |
| 12.5.2 | Uploaded files never run as HTML or script | 1 | Met | Non-media files download; SVG never inline; `nosniff`; `test_media_is_served_only_inside_the_media_folder`; `test_uploaded_polyglots_svg_and_path_tricks_end_up_harmless` (team/redteam). |
| 12.6.1 | An allow list of places the server may call | 1 | Partly | The code calls only fixed addresses and known push hosts. A network allow list for outbound traffic is Supreme IT's (README "Put it on Supreme's servers", item 6). |

## V13 API and web service

| # | Requirement | L | Status | Proof, reason or owner |
|---|---|---|---|---|
| 13.1.1 | The same parsers everywhere, so addresses can't be read two ways | 1 | In flight | On `main` the push check and the sending library read `https://10.0.0.5\@fcm.googleapis.com/` differently (RT-01). Fixed on team/redteam (`test_push_endpoints_that_two_url_readers_see_differently_are_refused`). |
| 13.1.3 | No secrets in API addresses | 1 | Met | None. Push addresses travel in the body. |
| 13.1.4 | Checks at the address and at the item | 2 | Met | `LoginRequiredMiddleware` for every address, then per-item checks (1.4.4). |
| 13.1.5 | Unexpected content types refused | 2 | Fixed here | The two JSON endpoints answer 415 to anything but JSON (`hub/account.py push_subscribe`, `push_unsubscribe`); `test_13_2_5_push_sign_up_only_takes_json`. |
| 13.2.1 | Only valid HTTP methods | 1 | Met | `require_POST` on every change; `test_every_change_refuses_a_plain_link` (team/redteam). |
| 13.2.2 | JSON checked against a schema | 1 | Met | The push sign-up checks keys, types, lengths and patterns (`hub/account.py`). |
| 13.2.3 | Cookie-based services protected from CSRF | 1 | Met | The page scripts send the form token as `X-CSRFToken` (`hub/static/hub/app.js`); see 4.2.2. |
| 13.2.5 | The incoming Content-Type checked | 2 | Fixed here | As 13.1.5. |
| 13.2.6 | Messages not changed in transit | 2 | Supreme | TLS (9.1.1). |
| 13.3.1 | SOAP checked against XSD | 1 | N/A | No SOAP. |
| 13.3.2 | SOAP payload signed | 2 | N/A | No SOAP. |
| 13.4.1 | GraphQL query limits | 2 | N/A | No GraphQL. |
| 13.4.2 | GraphQL checks in the business layer | 2 | N/A | No GraphQL. |

## V14 Configuration

| # | Requirement | L | Status | Proof, reason or owner |
|---|---|---|---|---|
| 14.1.1 | Secure, repeatable build and deployment | 2 | In flight | `Dockerfile` and `docker-compose.yml`. CI build: team/foundations. |
| 14.1.2 | Compiler hardening flags | 2 | N/A | The hub has no compiled code of its own. |
| 14.1.3 | Server settings hardened as the framework advises | 2 | In flight | Django's deploy check passes with production defaults on team/hardening (`test_production_settings_pass_djangos_deploy_check`). On `main` it warns about HTTPS redirect and HSTS until set. |
| 14.1.4 | Redeploy from scripts or a runbook, or restore from backups | 2 | In flight | team/handover INSTALL.md and RUNBOOK.md; team/reliability backups and `restore.sh`. |
| 14.2.1 | Components up to date, checked in the build | 1 | In flight | pip-audit and Dependabot: team/foundations. Monthly patching (README "Before go-live"). |
| 14.2.2 | Unneeded features and samples removed | 1 | Met | The demo commands refuse to run with `DEBUG` off unless forced (`seed_demo`, `demo_logins`); no sample apps. |
| 14.2.3 | Subresource Integrity for outside assets | 1 | N/A | Nothing is loaded from outside. |
| 14.2.4 | Components from trusted, maintained repositories | 2 | Met | PyPI and official Docker images (`python`, `postgres`, `nginx`). |
| 14.2.5 | A software bill of materials | 2 | Not met | `requirements.txt` pins the direct libraries only. team/foundations adds one to CI. |
| 14.2.6 | Third-party libraries sandboxed | 2 | Partly | ffmpeg runs as its own process with a timeout; Pillow runs in the app with a pixel limit. Accepted. |
| 14.3.2 | Debug modes off in production | 1 | Met | `DEBUG` comes from the environment and is off by default (`config/settings.py`). |
| 14.3.3 | No version numbers in headers | 1 | Met | `server_tokens off` (`deploy/nginx.conf`); nginx replaces gunicorn's `Server` header; Django adds none. |
| 14.4.1 | Every answer has a Content-Type, with a charset for text | 1 | Partly | Pages and JSON are UTF-8. The push worker (`text/javascript`) and the plain icon (`image/svg+xml`) name no charset; both are fixed ASCII files, and `nosniff` is on. Accepted. |
| 14.4.2 | API answers are `Content-Disposition: attachment` | 1 | Fixed here | Every JSON answer (`hub/security.py security_headers`); `test_8_2_1_..._and_14_4_2_json_downloads`. |
| 14.4.3 | A Content Security Policy | 1 | Partly | On every answer from the app (`hub/security.py CONTENT_SECURITY_POLICY`; `test_security_headers_block_foreign_scripts_and_framing`). Files nginx sends don't get it (RT-12): team/hardening. |
| 14.4.4 | `X-Content-Type-Options: nosniff` on every answer | 1 | Partly | Django adds it to every app answer, and nginx to uploaded files. nginx's own answers (429, 413) don't have it: team/hardening adds it with `always`. |
| 14.4.5 | HSTS on every answer, with subdomains | 1 | In flight | team/hardening: one year with `includeSubDomains`, on unless `DEBUG`. |
| 14.4.6 | A suitable Referrer-Policy | 1 | Met | `same-origin` (`config/settings.py`); links in posts are `noreferrer` (`hub/richtext.py`). |
| 14.4.7 | No framing by other sites | 1 | Met | `X-Frame-Options: DENY` and `frame-ancestors 'none'`; `test_security_headers_block_foreign_scripts_and_framing`; `test_no_page_can_be_framed_by_another_site` (team/redteam). |
| 14.5.1 | Only the HTTP methods in use accepted, others logged | 1 | Partly | Changes refuse GET (405). nginx passes other methods to the app, which answers them like GET. team/hardening limits nginx to GET, HEAD and POST. |
| 14.5.2 | The Origin header isn't used for access decisions | 1 | Met | Only Django's CSRF check reads it, as an extra check; access uses the session. |
| 14.5.3 | CORS with a strict allow list, never "null" | 1 | Met | The hub sends no CORS headers: same-site only. |
| 14.5.4 | Headers from a trusted proxy are checked | 2 | In flight | `X-Forwarded-For` only from `TRUSTED_PROXY` (`deploy/nginx.conf`). On `main` nginx passes on anyone's `X-Forwarded-Proto`; team/hardening only takes it from the proxy. |

## Fixed on this branch

| # | What changed | Code | Test (`hub/tests_asvs.py`) |
|---|---|---|---|
| 2.1.1 | Passwords need 12 characters | `config/settings.py` `AUTH_PASSWORD_VALIDATORS` | `test_2_1_1_passwords_need_at_least_12_characters` |
| 3.3.1, 8.2.3 | Sign out also signs the browser out of Entra ID | `hub/auth.py provider_logout_url`, `config/settings.py OIDC_OP_LOGOUT_URL_METHOD`, `hub/urls.py` and `config/urls.py` use `OIDCLogoutView` | `test_3_3_1_signing_out_also_signs_the_browser_out_of_microsoft`, `test_without_single_sign_on_sign_out_goes_to_the_sign_in_page` |
| 3.4.4 | `__Host-sessionid` in production | `config/settings.py SESSION_COOKIE_NAME` | `test_3_4_4_production_session_cookie_is_host_only_and_single_sign_on_signs_out_of_microsoft` |
| 7.2.2 | Every 403 logged as `access_denied` | `hub/security.py log_refusals`, last in `MIDDLEWARE` | `test_7_2_2_refused_requests_are_logged_with_who_and_where` |
| 8.2.1, 8.2.3 | Signed-in answers are `private, no-store` | `hub/security.py security_headers` | `test_8_2_1_signed_in_pages_are_never_kept_by_the_browser_and_14_4_2_json_downloads` |
| 12.3.4, 14.4.2 | JSON answers download under a fixed name | `hub/security.py security_headers` | the same test |
| 13.1.5, 13.2.5 | Push sign-up and sign-off only take JSON | `hub/account.py push_subscribe`, `push_unsubscribe` | `test_13_2_5_push_sign_up_only_takes_json` |

## Partly met and not met: who does what

"Accepted" means the security owner accepts the gap for go-live, for the reason in the row above; it is looked at
again at each threat model review.

| # | Gap | Owner | Decision |
|---|---|---|---|
| 1.2.4, 4.3.1 | The break-glass password has no MFA | team/handover (RUNBOOK.md: switch on only in an emergency, change the password after) | Accepted |
| 1.6.2, 2.10.3, 6.4.1, 6.4.2 | Secrets in `.env`, not a vault | Supreme IT | Accepted (K7) |
| 1.9.1, 9.2.2 | Plain links inside Supreme's network and the server | Supreme IT (TLS from proxy to nginx if wanted) | Accepted (K8) |
| 1.12.2, 14.4.3 | Files nginx sends lack the CSP and frame headers (RT-12) | team/hardening (`deploy/nginx.conf`) | Fix before go-live |
| 2.1.2 | Passwords over 128 characters aren't refused | None | Accepted |
| 2.1.8 | No password strength meter | None | Accepted |
| 2.1.12 | No "show password" button | None | Accepted |
| 2.4.5 | No secret salt (pepper) for passwords | None | Accepted |
| 2.5.4 | The break-glass account is shared by IT | team/handover (RUNBOOK.md) | Accepted |
| 2.10.1 | Fixed database passwords and push key | team/handover (rotation in RUNBOOK.md) | Accepted |
| 3.3.4 | No "your devices" page to end other sessions | team/hardening, after the pilot | Accepted for go-live (K6) |
| 3.3.1 | Microsoft must know `/login/` to send people back after sign-out | team/handover (ENTRA-SETUP.md step 1: add `https://<hub address>/login/` as a redirect URI) | Fix before go-live |
| 4.3.3 | No step-up sign-in for admin actions | None | Accepted |
| 5.2.2 | A NUL character in a search box gives an error page on Postgres (RT-10) | team/hardening (one middleware, handed on by team/redteam) | Fix before go-live |
| 7.1.3 | Form mistakes aren't logged | None | Accepted |
| 7.2.2 | `access_denied` isn't in the runbook's alert list yet | team/handover (RUNBOOK.md "Alerts": "WARNING. Someone was refused a page or a change. A burst from one person: they are probing; check what they tried.") | Add |
| 9.1.2, 9.1.3 | The go-live list doesn't test the proxy's TLS | team/handover (GO-LIVE.md: a TLS test of the live address shows only TLS 1.2 and 1.3 and strong ciphers) | Add |
| 8.1.4, 11.1.7, 11.1.8 | Alert rules for bursts of `rate_limited` and `access_denied` | team/reliability (MONITORING.md), Supreme IT (SIEM) | Fix before go-live |
| 8.3.5 | Moderators opening content in the admin isn't logged | team/compliance decides in the DPIA; team/hardening builds it if needed | Decide before the pilot |
| 11.1.2 | No "too fast" check per step | None | Accepted |
| 11.1.6 | Two requests at the same moment can both get in under a limit | team/hardening (the limits) | Accepted |
| 12.4.2 | No virus scan of uploads | Supreme IT decides; team/hardening adds a scanner | Accepted for now (K5) |
| 12.6.1 | No outbound network allow list | Supreme IT (firewall to the hosts in README item 6) | Fix before go-live |
| 14.2.5 | No software bill of materials | team/foundations (CI) | Fix before go-live |
| 14.2.6 | Pillow runs inside the app | None | Accepted |
| 14.4.1 | Two fixed files name no charset | None | Accepted |
| 14.4.4 | nginx's own answers lack `nosniff` | team/hardening (`add_header ... always`) | Fix before go-live |
| 14.5.1 | nginx passes every HTTP method | team/hardening (`deploy/nginx.conf`) | Fix before go-live |

## Approvals

| | |
|---|---|
| Supreme IT security, OWASP ASVS 4.0.3 Level 2 as the hub's baseline | Signed off (assumed for delivery, 2026-11-20) |
| Supreme IT security, the accepted gaps above | Signed off (assumed for delivery, 2026-11-20) |
