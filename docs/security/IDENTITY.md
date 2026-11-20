# Sign-in, sessions and leavers

For Supreme IT and the security owner. How people get into One Supreme, how long they stay signed in, and how
they lose access. Each rule below has a test in `hub/tests_identity.py`, listed at the end. The tests fake
Microsoft Entra ID (no network) and use `config/settings.py` exactly as the live server loads it.

The Entra side (app registration, certificate, Conditional Access) is in `docs/operations/ENTRA-SETUP.md`. What to
do day to day (urgent leavers, re-hires, break-glass) is in `docs/operations/RUNBOOK.md`.

## Who can sign in

Someone can sign in only if all of these are true:

- They have an account in Supreme's own Entra ID tenant, and the app is assigned to them (ENTRA-SETUP.md, step 5).
- Their email ends in one of `ALLOWED_EMAIL_DOMAINS` (`supreme.co.uk`). This keeps directory guests out, since
  their addresses belong to other companies.
- Their hub account isn't switched off.

The hub won't start with the shared Microsoft addresses (`common`, `organizations`, `consumers`) in its settings,
or without `ALLOWED_EMAIL_DOMAINS`. Put the **tenant ID** in the three Microsoft addresses, not a domain name: the
hub checks that each token came from that tenant. If either the sign-in or the token address is a Microsoft one,
the hub won't start unless they are exactly `https://login.microsoftonline.com/<tenant ID>/oauth2/v2.0/authorize`
and `.../token`, in lower case. A domain name there would refuse everyone at their first sign-in. Another Microsoft
host (such as `login.microsoft.com`, `login.windows.net` or `sts.windows.net`) would quietly turn off the tenant
check and the leaver check, and the pages' security policy (below) wouldn't let the browser go on to it.

Password sign-in is off unless `ALLOW_PASSWORD_LOGIN=1`, which is only for the break-glass account (below).

## Signing in, step by step

1. "Sign in with your work account" sends the browser to Microsoft. The hub keeps three random values in the
   browser's session: the **state** (Microsoft's answer must come back to this browser), the **nonce** (the ID
   token must be for this sign-in) and a **PKCE** code verifier (only the hub can swap Microsoft's code for tokens).
2. Microsoft checks the password and multi-factor sign-in (MFA), then sends the browser back with a one-time code.
3. The hub swaps the code for tokens directly with Microsoft, using the PKCE verifier and the app's client secret.
   The operations work (team/handover, ENTRA-SETUP.md) replaces the client secret with a certificate.
4. The hub checks the ID token. It must be signed with the tenant's keys (RS256), be issued by Supreme's tenant,
   be made for this app, carry the nonce, and be in date. A minute's margin allows for clock differences.
   Microsoft signs every organisation's tokens with the same keys, so the tenant and app checks are what keep
   other organisations out.
5. The hub reads the person's email and name from Microsoft. The email must be in `ALLOWED_EMAIL_DOMAINS`.
6. The hub finds the account by Microsoft's permanent ID for the person (`oid`), so a changed email or name keeps
   the same account. On a first sign-in it links an unlinked account with the same email, or creates a new one:
   no password, no admin rights, and the house rules come first.
7. A switched-off account is refused.
8. The person gets a new session with a new id, so a session id planted in the browser before sign-in is useless.

Every call to Microsoft (token, keys, userinfo) gives up after 10 seconds (`OIDC_TIMEOUT`). Without a limit, a
call that never returns would hold one of the server's request threads for good; once all 16 are held, the hub
stops for everyone.

**When Microsoft's answer is refused.** If Microsoft says no (it sends an error back), or any check above fails,
or Microsoft doesn't answer in time or answers with an error, the person sees "We couldn't sign you in" and is
signed out. The security log gets `sign_in_rejected` with the reason, and Microsoft's error code when it sent one.

**When the answer isn't for a sign-in this browser started.** A link to the hub's callback address, a finished
sign-in sent again, or a state lost when two tabs saved the session at the same moment: the browser goes to the
sign-in page and the log gets `sign_in_ignored` ("no sign-in started with this state"), but nobody is signed
out. Someone who was signed in carries on. Anyone can send these, so they are logged at INFO under their own name
and can't set off the SIEM's alerts on `sign_in_rejected`.

**Where the browser goes next.** After a sign-in or a 15-minute check, the hub sends the browser back to the page
the person was on, but only if that page is on the hub. A crafted link such as
`https://hub.supreme.co.uk//evil.example/` ends on the hub's home page, not on another site.

## Staying signed in

- **The cookie.** It holds only a random key; the session itself is on the server. Outside development it is
  Secure, HttpOnly and SameSite=Lax (`config/settings.py`).
- **Every 15 minutes**, on the next page the person opens, the hub checks with Microsoft in the background, with
  no prompt. If Microsoft refuses (account disabled, sessions revoked, Conditional Access now blocks), or the
  hub's own checks above refuse, the person is signed out. When the check is due, a background request (chat's
  check for new messages every 4 seconds, name suggestions) gets a "check first" answer instead; chat then
  reloads the page, which runs the check. A form send itself isn't held up, but the page it goes on to runs the
  check. Browsers allow that trip to Microsoft only because each page's security policy (`form-action` in
  `hub/security.py`) names `https://login.microsoftonline.com`. Files aren't re-checked; the leaver check covers
  them.
- **Idle limit: 12 hours.** A session that nothing has renewed for 12 hours ends, with nothing in the security
  log. The 15-minute check renews it while someone uses the hub. An open chat page renews it too, with nobody at
  the desk: its background check reloads the page every 15 minutes, so only the 24-hour limit ends that session.
  This is `SESSION_COOKIE_AGE`, set in `config/settings.py` with the hardening work (without it Django's default
  is 2 weeks).
- **Absolute limit: 24 hours.** A day after signing in, the hub signs everyone out, however busy they are, and
  logs `session_expired` and `sign_out`. Without this, the 15-minute check could keep one session going for ever.
  The person clicks "Sign in with your work account" again, and Microsoft usually lets them straight through.
  This is `MAX_SESSION_AGE` in `hub/auth.py`.
- **Signing out** (Menu, Sign out, or the admin's Log out) deletes the session on the server, so a copied cookie
  stops working. Then it sends the browser to Microsoft's sign-out address; each page's `form-action` allows that
  address, or the browser would block the trip. Microsoft asks which account to sign out of. Once the person picks
  theirs, Microsoft signs that browser out of Outlook, Teams and other Microsoft pages open in it, and shows its own
  "signed out" page. Only then does the next person on a shared computer who clicks "Sign in" have to sign in as
  themselves: someone who walks away from Microsoft's account list leaves their Microsoft session open (the hub's
  session has already ended). Coming back to the hub's sign-in page instead would need
  `https://hub.supreme.co.uk/login/` added as a redirect URI in the app registration, and that address added to the
  sign-out in `hub/auth.py`.
- Sign out from a tab whose session has already ended goes straight to the sign-in page.
- The break-glass account never signed in to Microsoft, so its sign-out goes straight back to the hub's sign-in
  page.
- **A link can't sign anyone out.** Sign out is a button that sends a form with the page's security token;
  opening `/logout/` as a link is refused. An answer to a sign-in the browser didn't start is ignored (above).

## Leavers

When IT disables or deletes someone's Entra account (Supreme's usual leaver process):

- **Within 15 minutes** the leaver check (`sync_directory`, run every 15 minutes) switches off their hub account.
  Switching an account off deletes all its sessions on the server, and a switched-off account is refused on every
  request from every device: pages, form sends and files. That is what "signed out everywhere" means here. If
  they open a page sooner, the 15-minute check above usually signs them out first.
- For an **urgent leaver**, also untick **Active** in the admin: that deletes their sessions at once (RUNBOOK.md).
- The check compares linked accounts by `oid`, and accounts not yet linked by email. Password accounts, such as the
  break-glass admin, are left alone; an account linked to single sign-on is checked even if someone gave it a
  password.
- **Safety limit.** If one run would switch off more than a fifth of accounts (and more than 5), it changes nothing
  and fails. A lost permission or an empty answer from Microsoft must not lock out the company.
- **Failures** are logged every time as `directory_sync_failed`, at ERROR, which the SIEM alerts on (RUNBOOK.md).
  The 05:00 UTC run also emails `ADMIN_EMAILS`
  ("Staff hub: leaver check failed"). The other runs don't email, so a long outage sends one email a day, not 96.
  Until it is fixed, the 15-minute check on page loads still signs leavers out.
- The leaver check never switches anyone back on.
- `LEAVER_RETENTION_DAYS` after the switch-off, the clean-up removes the account
  (`docs/compliance/data-inventory-and-retention.md`). Ticking Active again stops that clock.

## Re-hires

- **Same Entra account, turned back on.** IT turns it on first, then an admin ticks **Active**. The person signs in
  to their old account, with their old posts. Their old sessions went when the account was switched off, so every
  device signs in afresh. If Active is ticked first, the next leaver check switches the account off again within
  15 minutes.
- **A new Entra account** (a new `oid`, the same email) is refused, because the email belongs to the old account,
  which is linked to the old Entra account. An admin ticks **Active** on the old account and runs the action
  **Unlink single sign-on**. The next sign-in links the new Entra account to it.
- Before ticking Active, check **Staff status**, **Superuser status** and **Groups**: the account comes back with
  whatever it had.
- If the clean-up has already removed the old account, the first sign-in makes a new one.

## Admins, MFA and the break-glass account

- Admins sign in like everyone else, with their work account. `/admin/login/` sends them to the hub's sign-in page.
  With `ALLOW_PASSWORD_LOGIN=0` there is no other way in, so Entra's MFA policy covers every admin.
- **The hub doesn't check for MFA itself.** Conditional Access ("One Supreme: require MFA", ENTRA-SETUP.md step 7)
  makes Microsoft ask for it before it sends anyone back. GO-LIVE.md item 16 checks it in the Entra sign-in log.
- **The break-glass account** is the one superuser with a password. Its email is outside `ALLOWED_EMAIL_DOMAINS`,
  so single sign-on can never link to it, and its password is only in IT's password manager. It works only while
  `ALLOW_PASSWORD_LOGIN=1` (RUNBOOK.md, Break-glass sign-in). It skips Entra and MFA, so every password sign-in
  while single sign-on is on emails `ADMIN_EMAILS` ("Staff hub: break-glass sign-in") and is logged as `sign_in`.
  It has a password only, no hardware key.
- **Only the break-glass account can use a password while single sign-on is on.** Password sign-in refuses any
  account linked to single sign-on, or with an email in `ALLOWED_EMAIL_DOMAINS`, even if someone gave it a
  password, so nobody else can skip MFA while break-glass is switched on. Without single sign-on (development and
  demos) any password account works.
- The quarterly access review (RUNBOOK.md) checks that the break-glass account is the only one with a password.

## Security log events

| Event | When |
|---|---|
| `sign_in` | Someone signed in, with single sign-on or a password. |
| `sign_out` | Someone signed out with the button, the 24-hour limit ended their session, or a refused check signed them out. The 12-hour idle limit logs nothing. |
| `sign_in_failed` | A password was wrong or not allowed for that account, or single sign-on found no account it could let in. |
| `sign_in_rejected` | Single sign-on refused a sign-in or 15-minute check the browser started; `reason`, `error` or `email` says why. |
| `sign_in_ignored` | INFO: an answer came to the callback address for a sign-in the browser didn't start (a link or a replay). Nobody is signed out. |
| `session_expired` | The 24-hour limit signed someone out. |
| `account_deactivated` | The leaver check switched an account off. |
| `directory_sync_failed` | The leaver check couldn't run, or stopped at the safety limit. |
| `sso_unlinked` | An admin unlinked an account from single sign-on. |

## What the tests can't show

The tests fake Microsoft. On the real tenant, ENTRA-SETUP.md step 9 checks a sign-in (with MFA in the Entra
sign-in log) and runs `sync_directory --dry-run`. That Microsoft refuses the background check for a disabled
account is Microsoft's behaviour; the hub's side of it (an error back means signed out) is tested. The same goes
for sign-out: the tests show the hub sends the browser to Microsoft's sign-out address; that Microsoft then ends
its own session is checked on the real tenant by signing out and clicking "Sign in" again, which must ask who you
are. That the 10-second limit frees the server's threads is how the request library and gunicorn work, checked by
reading them, not by a test.

## The tests

All in `hub/tests_identity.py`.

| Rule | Test |
|---|---|
| Live settings: PKCE, RS256, 15-minute check, 10-second limit, sign-out to Microsoft, no password backend, shared addresses and other Microsoft hosts or spellings refused | `test_production_settings_turn_on_every_check` |
| PKCE, state and nonce sent; a new session id at sign-in | `test_sign_in_uses_pkce_state_and_nonce_and_starts_a_new_session` |
| First sign-in creates the account correctly | `test_the_first_sign_in_creates_the_account_from_the_directory` |
| Wrong state, wrong nonce, no sign-in started: refused and logged | `test_a_reply_that_does_not_match_the_sign_in_it_started_is_refused` |
| A replay, or a link to the callback, signs nobody out and is logged at INFO as `sign_in_ignored` | `test_a_reply_to_a_sign_in_this_browser_did_not_start_signs_nobody_out` |
| Another tenant, another app, expired, no expiry, wrong key: refused; small clock difference: fine | `test_only_a_current_token_from_supremes_tenant_for_this_app_gets_in` |
| Email outside the company domains, or none: refused | `test_an_address_outside_the_company_domains_is_refused` |
| Switched-off account: refused | `test_a_switched_off_account_cannot_sign_in` |
| Email change keeps the account | `test_an_email_change_keeps_the_same_account` |
| The 15-minute check: passes quietly, signs out on Microsoft's refusal (logged with its error code) or the hub's; `form-action` allows its trip to Microsoft | `test_the_15_minute_recheck_signs_people_out_when_it_fails` |
| After the check, a crafted `//evil.example/` link still ends on the hub | `test_after_the_recheck_the_browser_only_goes_to_a_page_on_the_hub` |
| Microsoft not answering, or answering 503: signed out, logged, no error page; every call has the 10-second limit | `test_microsoft_being_slow_or_down_signs_out_instead_of_failing_the_page` |
| Sign out deletes the session and goes to Microsoft's sign-out, which `form-action` allows; a link can't sign out | `test_signing_out_ends_the_session_and_signs_the_browser_out_of_microsoft` |
| The admin's Log out does the same | `test_the_admins_log_out_also_signs_the_browser_out_of_microsoft` |
| Leavers switched off, their sessions deleted, and refused on every device, for pages, posts and files | `test_leavers_are_switched_off_and_signed_out_everywhere` |
| Switching an account off deletes its sessions, so switching it on again needs a fresh sign-in | `test_switching_an_account_off_deletes_its_sessions` |
| The leaver check runs every 15 minutes; the 05:00 run emails | `test_the_leaver_check_runs_every_15_minutes_and_emails_failures_from_its_daily_run` |
| Leaver check failures: logged every time, emailed from the daily run | `test_a_failing_leaver_check_is_logged_every_time_and_emailed_from_the_daily_run` |
| Linked accounts checked even with a password; break-glass left alone | `test_an_account_linked_to_single_sign_on_is_checked_even_with_a_password` |
| Re-hire, same or new Entra account | `test_a_rehire_gets_their_own_account_back` |
| Signing out ends the session on the server (without single sign-on); signing out again from an ended session goes to the sign-in page | `test_signing_out_ends_the_session_on_the_server` |
| Idle and absolute limits | `test_the_idle_and_absolute_limits` |
| Password sign-in off unless `ALLOW_PASSWORD_LOGIN=1` | `test_password_sign_in_is_off_unless_allow_password_login_is_set` |
| Break-glass sign-in emails IT; its sign-out goes back to the sign-in page | `test_the_break_glass_sign_in_alerts_it` |
| While single sign-on is on, only the break-glass account can use a password | `test_while_single_sign_on_is_on_only_the_break_glass_account_can_use_a_password` |

## Sign-off

| What | Who | Status |
|---|---|---|
| Sign-in, session limits and leaver handling as described here | Supreme IT and the security owner | Signed off (assumed for delivery, 2026-11-20) |
| Conditional Access policy requiring MFA for the hub | Supreme IT | Signed off (assumed for delivery, 2026-11-20) |
| Sign out also signs the browser out of Microsoft | Supreme IT | Signed off (assumed for delivery, 2026-11-20) |
