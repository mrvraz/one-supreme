"""Sign-in, sessions and leavers, end to end, with Microsoft Entra ID faked (no network).

The fake signs ID tokens with a throwaway key and answers the three addresses the hub calls: the token address,
the tenant's keys and the userinfo address. The settings are config/settings.py as Supreme's server loads them.
docs/security/IDENTITY.md describes what these tests show.
"""

import functools
import json
import os
import runpy
import time
from base64 import urlsafe_b64encode
from datetime import datetime, timedelta, timezone as dt_timezone
from hashlib import sha256
from io import StringIO
from unittest import mock
from urllib.parse import parse_qs, urlsplit

import jwt
import requests as real_requests
from cryptography.hazmat.primitives.asymmetric import rsa
from django.conf import settings
from django.contrib.auth import SESSION_KEY
from django.contrib.sessions.models import Session
from django.core import mail
from django.core.exceptions import ImproperlyConfigured
from django.core.management import CommandError, call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .auth import MAX_SESSION_AGE
from .models import Post, User

TENANT = "5f0c2e61-0000-4000-8000-00000000c0de"  # made up
OTHER_TENANT = "9a1b7d33-0000-4000-8000-0000000bad00"
CLIENT_ID = "one-supreme-test-app"
ENTRA = f"https://login.microsoftonline.com/{TENANT}"
JWKS_URL = f"{ENTRA}/discovery/v2.0/keys"
OID = "1e6f9a20-0000-4000-8000-000000000001"  # Microsoft's permanent ID for the test person
EMAIL = "alex.example@supreme.co.uk"
MODEL_BACKEND = "django.contrib.auth.backends.ModelBackend"
SSO_ENV = {
    "DEBUG": "1",
    "OIDC_RP_CLIENT_ID": CLIENT_ID,
    "OIDC_RP_CLIENT_SECRET": "not-a-real-secret",
    "OIDC_RP_CLIENT_CERT_FILE": "",
    "OIDC_OP_AUTHORIZATION_ENDPOINT": f"{ENTRA}/oauth2/v2.0/authorize",
    "OIDC_OP_TOKEN_ENDPOINT": f"{ENTRA}/oauth2/v2.0/token",
    "OIDC_OP_USER_ENDPOINT": "https://graph.microsoft.com/oidc/userinfo",
    "OIDC_OP_JWKS_ENDPOINT": JWKS_URL,
    "ALLOWED_EMAIL_DOMAINS": "supreme.co.uk",
    "ALLOW_PASSWORD_LOGIN": "0",
}
TENANT_KEY, STRANGER_KEY = (rsa.generate_private_key(public_exponent=65537, key_size=2048) for _ in range(2))
JWK = {**json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(TENANT_KEY.public_key())), "kid": "tenant-key"}


def production_settings(**env):
    """config/settings.py as the hub loads it on Supreme's server: single sign-on with Entra ID on."""
    with mock.patch.dict(os.environ, {**SSO_ENV, **env}):
        return runpy.run_path(str(settings.BASE_DIR / "config/settings.py"))


@functools.cache
def sign_in_settings(**env):
    loaded = production_settings(**env)
    names = ("AUTHENTICATION_BACKENDS", "MIDDLEWARE", "ALLOWED_EMAIL_DOMAINS", "ALLOW_PASSWORD_LOGIN", "LOGIN_REDIRECT_URL_FAILURE")
    return {name: value for name, value in loaded.items() if name.startswith("OIDC_") or name in names}


def id_token(claims, key=TENANT_KEY):
    now = int(time.time())
    body = {"iss": f"{ENTRA}/v2.0", "aud": CLIENT_ID, "tid": TENANT, "oid": OID, "sub": "pairwise-sub",
            "iat": now, "nbf": now, "exp": now + 3600, **claims}
    return jwt.encode({k: v for k, v in body.items() if v is not None}, key, "RS256", headers={"kid": "tenant-key"})


def reply(body):
    return mock.Mock(status_code=200, headers={"content-type": "application/json"}, **{"json.return_value": body})


def query(response):
    return {name: values[0] for name, values in parse_qs(urlsplit(response["Location"]).query).items()}


def run_leaver_check(directory, *args, error=None):
    """sync_directory against a fake Microsoft Graph that lists `directory`."""
    with mock.patch("hub.management.commands.sync_directory.requests") as requests, override_settings(
        OIDC_OP_TOKEN_ENDPOINT=SSO_ENV["OIDC_OP_TOKEN_ENDPOINT"], OIDC_RP_CLIENT_ID=CLIENT_ID,
        OIDC_RP_CLIENT_SECRET=SSO_ENV["OIDC_RP_CLIENT_SECRET"], ADMINS=[("IT", "it@supreme.co.uk")],
    ):
        requests.RequestException = real_requests.RequestException
        requests.post.return_value = reply({"access_token": "graph-token"})
        requests.get.return_value = reply({"value": directory})
        requests.get.side_effect = error
        call_command("sync_directory", *args, stdout=StringIO())


class SSOTestCase(TestCase):
    """Tests run with the production sign-in settings, so they also prove those settings."""

    env = {}

    def setUp(self):
        overrides = override_settings(**sign_in_settings(**self.env))
        overrides.enable()
        self.addCleanup(overrides.disable)

    def start_sign_in(self, client=None):
        """The browser clicks "Sign in with your work account" and is sent to Microsoft."""
        response = (client or self.client).get(reverse("oidc_authentication_init"), {"next": "/people/"})
        self.assertTrue(response["Location"].startswith(f"{ENTRA}/oauth2/v2.0/authorize?"))
        return query(response)

    def finish_sign_in(self, request, client=None, userinfo=None, key=TENANT_KEY, state=None, **claims):
        """Microsoft sends the browser back with a code, which the hub swaps for tokens, then reads the userinfo."""
        info = {"sub": "pairwise-sub", "email": EMAIL, "given_name": "Alex", "family_name": "Example", **(userinfo or {})}
        token = id_token({"nonce": request.get("nonce"), **claims}, key)
        with mock.patch("mozilla_django_oidc.auth.requests") as requests:
            requests.post.return_value = reply({"id_token": token, "access_token": "access-token", "token_type": "Bearer"})
            requests.get.side_effect = lambda url, **kwargs: reply({"keys": [JWK]} if url == JWKS_URL else info)
            response = (client or self.client).get(
                reverse("oidc_authentication_callback"), {"code": "code-from-entra", "state": state or request["state"]}
            )
        self.token_request = requests.post.call_args.kwargs["data"] if requests.post.called else None
        return response

    def sign_in(self, **kwargs):
        return self.finish_sign_in(self.start_sign_in(kwargs.get("client")), **kwargs)

    def assert_refused(self, response, client=None):
        self.assertRedirects(response, "/login/?error=sso", fetch_redirect_response=False)
        self.assertNotIn(SESSION_KEY, (client or self.client).session)

    def signed_in_user(self):
        return User.objects.get(pk=self.client.session[SESSION_KEY])


class SignInTests(SSOTestCase):
    def test_production_settings_turn_on_every_check(self):
        loaded = production_settings()
        self.assertTrue(loaded["OIDC_USE_PKCE"])
        self.assertEqual(loaded["OIDC_RP_SIGN_ALGO"], "RS256")
        self.assertEqual(loaded["OIDC_RENEW_ID_TOKEN_EXPIRY_SECONDS"], 15 * 60)
        self.assertEqual(loaded["AUTHENTICATION_BACKENDS"], ["hub.auth.EmployeeOIDCBackend"])
        self.assertIn("mozilla_django_oidc.middleware.SessionRefresh", loaded["MIDDLEWARE"])
        self.assertIn("hub.auth.session_limit", loaded["MIDDLEWARE"])
        for shared in ("common", "organizations"):  # these let in people from any organisation
            with self.subTest(shared), self.assertRaisesMessage(ImproperlyConfigured, "own tenant ID"):
                production_settings(OIDC_OP_AUTHORIZATION_ENDPOINT=f"https://login.microsoftonline.com/{shared}/oauth2/v2.0/authorize")
        with self.assertRaisesMessage(ImproperlyConfigured, "ALLOWED_EMAIL_DOMAINS"):
            production_settings(ALLOWED_EMAIL_DOMAINS="")

    def test_sign_in_uses_pkce_state_and_nonce_and_starts_a_new_session(self):
        request = self.start_sign_in()
        self.assertEqual((request["response_type"], request["client_id"]), ("code", CLIENT_ID))
        self.assertEqual(request["redirect_uri"], "http://testserver/oidc/callback/")
        self.assertEqual(request["code_challenge_method"], "S256")
        self.assertGreaterEqual(min(len(request["state"]), len(request["nonce"])), 32)
        before = self.client.session.session_key  # e.g. one an attacker planted in this browser
        with self.assertLogs("hub.security", "INFO") as logs:
            response = self.finish_sign_in(request)
        self.assertRedirects(response, "/people/", fetch_redirect_response=False)
        verifier = self.token_request["code_verifier"]
        self.assertEqual(urlsafe_b64encode(sha256(verifier.encode()).digest()).rstrip(b"=").decode(), request["code_challenge"])
        self.assertEqual(self.token_request["code"], "code-from-entra")
        self.assertNotEqual(self.client.session.session_key, before)
        self.assertEqual([r.getMessage() for r in logs.records], ["sign_in"])
        self.assertEqual(mail.outbox, [])  # only password sign-ins alert IT

    def test_the_first_sign_in_creates_the_account_from_the_directory(self):
        self.sign_in()
        alex = self.signed_in_user()
        self.assertEqual((alex.email, alex.get_full_name(), alex.sso_id), (EMAIL, "Alex Example", OID))
        self.assertFalse(alex.has_usable_password())  # no password, so the leaver check treats it as single sign-on
        self.assertFalse(alex.is_staff or alex.is_superuser)
        self.assertNotEqual(alex.username, EMAIL)  # generated, so it gives nothing away
        self.assertEqual(alex.policy_version, "")  # the house rules come first

    def test_a_reply_that_does_not_match_the_sign_in_it_started_is_refused(self):
        with self.assertLogs("hub.security", "WARNING") as logs:
            self.assert_refused(self.finish_sign_in(self.start_sign_in(), state="made-up-state"))
            self.assert_refused(self.finish_sign_in(self.start_sign_in(), nonce="made-up-nonce"))
        reasons = [r.details["reason"] for r in logs.records]
        self.assertIn("state not found", reasons[0])
        self.assertIn("Nonce verification failed", reasons[1])
        # A reply in a browser that never started a sign-in, and a finished sign-in replayed.
        stranger = Client()
        request = self.start_sign_in()
        self.assert_refused(self.finish_sign_in(request, client=stranger), stranger)
        self.finish_sign_in(request)
        with self.assertLogs("hub.security", "WARNING"):
            self.assert_refused(self.finish_sign_in(request))
        self.assertEqual(User.objects.count(), 1)

    def test_only_a_current_token_from_supremes_tenant_for_this_app_gets_in(self):
        tokens = {
            "another organisation": ({"iss": f"https://login.microsoftonline.com/{OTHER_TENANT}/v2.0", "tid": OTHER_TENANT}, TENANT_KEY),
            "another app": ({"aud": "someone-elses-app"}, TENANT_KEY),
            "expired": ({"iat": int(time.time()) - 7200, "exp": int(time.time()) - 3600}, TENANT_KEY),
            "no expiry": ({"exp": None}, TENANT_KEY),
            "not signed by the tenant's key": ({}, STRANGER_KEY),
        }
        for name, (claims, key) in tokens.items():
            with self.subTest(name), self.assertLogs("hub.security", "WARNING") as logs:
                self.assert_refused(self.finish_sign_in(self.start_sign_in(), key=key, **claims))
            self.assertIn("ID token refused", logs.records[-1].details["reason"])
        self.assertFalse(User.objects.exists())
        # A server clock a little behind Microsoft's still lets people in.
        soon = int(time.time()) + 30
        self.assertRedirects(self.sign_in(iat=soon, nbf=soon), "/people/", fetch_redirect_response=False)

    def test_an_address_outside_the_company_domains_is_refused(self):
        for email in ("guest@partner.example", "alex@supreme.co.uk.partner.example", None):
            with self.subTest(email), self.assertLogs("hub.security", "WARNING") as logs:
                self.assert_refused(self.sign_in(userinfo={"email": email}))
            self.assertEqual(logs.records[0].details["email"], email or "(none)")
        self.assertFalse(User.objects.exists())

    def test_a_switched_off_account_cannot_sign_in(self):
        User.objects.create_user("alex", EMAIL, sso_id=OID, is_active=False)
        with self.assertLogs("hub.security", "WARNING") as logs:
            self.assert_refused(self.sign_in())
        self.assertIn("account switched off", [r.details.get("reason") for r in logs.records])

    def test_an_email_change_keeps_the_same_account(self):
        alex = User.objects.create_user("alex", "alex.old-name@supreme.co.uk", sso_id=OID)
        self.sign_in()  # the directory now says alex.example@supreme.co.uk
        self.assertEqual(self.signed_in_user(), alex)
        alex.refresh_from_db()
        self.assertEqual(alex.email, EMAIL)
        self.assertEqual(User.objects.count(), 1)

    def test_the_15_minute_recheck_signs_people_out_when_it_fails(self):
        self.sign_in()
        User.objects.update(policy_version=settings.POLICY_VERSION)
        recheck = self.recheck_due()
        self.assertEqual(recheck["prompt"], "none")  # in the background: Microsoft shows nothing
        # It passes: same session, next check in 15 minutes.
        session_key = self.client.session.session_key
        self.assertRedirects(self.finish_sign_in(recheck), "/people/", fetch_redirect_response=False)
        self.assertEqual(self.client.session.session_key, session_key)
        self.assertAlmostEqual(self.client.session["oidc_id_token_expiration"], time.time() + 15 * 60, delta=60)
        # Microsoft refuses (account disabled, sessions revoked): it sends an error back.
        recheck = self.recheck_due()
        self.client.get(reverse("oidc_authentication_callback"), {"error": "login_required", "state": recheck["state"]})
        self.assertNotIn(SESSION_KEY, self.client.session)
        # Microsoft says yes but the hub's rules now say no, here an email outside the company domains.
        self.sign_in()
        with self.assertLogs("hub.security", "WARNING"):
            self.assert_refused(self.finish_sign_in(self.recheck_due(), userinfo={"email": "alex@new-employer.example"}))

    def recheck_due(self):
        session = self.client.session
        session["oidc_id_token_expiration"] = time.time() - 1  # 15 minutes have gone by
        session.save()
        response = self.client.get("/people/")
        self.assertTrue(response["Location"].startswith(f"{ENTRA}/oauth2/v2.0/authorize?"))
        return query(response)


class LeaverTests(SSOTestCase):
    def signed_in_device(self, user):
        device = Client()
        device.force_login(user, backend="hub.auth.EmployeeOIDCBackend")
        session = device.session
        session["oidc_id_token_expiration"] = time.time() + 15 * 60  # just re-checked with Microsoft
        session.save()
        return device

    def test_leavers_are_switched_off_and_signed_out_everywhere(self):
        leaver = User.objects.create_user("leaver", "leaver@supreme.co.uk", sso_id="oid-leaver", policy_version=settings.POLICY_VERSION)
        stayer = User.objects.create_user("stayer", "stayer@supreme.co.uk", sso_id="oid-stayer", policy_version=settings.POLICY_VERSION)
        devices = [self.signed_in_device(leaver) for _ in range(2)]  # a phone and a laptop
        stayers_phone = self.signed_in_device(stayer)
        self.assertEqual(devices[0].get(reverse("people")).status_code, 200)
        with self.assertLogs("hub.security", "INFO") as logs:
            run_leaver_check([
                {"id": "oid-stayer", "mail": "stayer@supreme.co.uk", "accountEnabled": True},
                {"id": "oid-leaver", "mail": "leaver@supreme.co.uk", "accountEnabled": False},  # disabled by IT
            ])
        self.assertEqual(logs.records[0].getMessage(), "account_deactivated")
        leaver.refresh_from_db()
        self.assertFalse(leaver.is_active)
        # Every request from every session is refused: pages, posts the 15-minute re-check doesn't cover, and files.
        for device in devices:
            for response in (
                device.get(reverse("people")),
                device.post(reverse("feed"), {"body": "Goodbye, all"}),
                device.get(reverse("media", args=["posts/x.jpg"])),
            ):
                self.assertTrue(response["Location"].startswith(reverse("login")), response)
        self.assertFalse(Post.objects.exists())
        self.assertEqual(stayers_phone.get(reverse("people")).status_code, 200)

    def test_the_leaver_check_runs_every_15_minutes_and_emails_failures_from_its_daily_run(self):
        from hub.management.commands import scheduler

        start = datetime(2026, 12, 1, 4, 0, tzinfo=dt_timezone.utc)
        clock = [start + timedelta(minutes=m) for m in range(62)]  # 04:00 to 05:01, a tick a minute
        ran = []

        class Stop(Exception):
            pass

        with (
            mock.patch.object(scheduler, "datetime", **{"now.side_effect": clock}),
            mock.patch.object(scheduler, "run", side_effect=lambda *job: ran.append(" ".join(job))),
            mock.patch("time.sleep", side_effect=[None] * (len(clock) - 1) + [Stop]),
            self.assertRaises(Stop),
        ):
            call_command("scheduler", stdout=StringIO())
        minutes, ticks = [], 0
        for job in ran:
            ticks += job == "tick"
            if job == "sync_directory --no-email":
                minutes.append(ticks - 1)
        self.assertEqual(minutes, [0, 15, 30, 45, 60])
        self.assertEqual(ran.count("sync_directory"), 1)  # 05:00, the run that emails

    def test_a_failing_leaver_check_is_logged_every_time_and_emailed_from_the_daily_run(self):
        for args, emails in ((["--no-email"], 0), ([], 1)):
            mail.outbox.clear()
            with self.subTest(args), self.assertLogs("hub.security", "ERROR") as logs, self.assertRaises(CommandError):
                run_leaver_check([], *args, error=real_requests.ConnectionError("Graph is down"))
            self.assertEqual(logs.records[0].getMessage(), "directory_sync_failed")
            self.assertEqual(len(mail.outbox), emails)
        self.assertEqual(mail.outbox[0].subject, "Staff hub: leaver check failed")
        self.assertIn("Graph is down", mail.outbox[0].body)

    def test_an_account_linked_to_single_sign_on_is_checked_even_with_a_password(self):
        linked = User.objects.create_user("linked", "linked@supreme.co.uk", "not-a-real-password", sso_id="oid-linked")
        breakglass = User.objects.create_superuser("breakglass", "breakglass@hub.invalid", "not-a-real-password")
        with self.assertLogs("hub.security", "INFO"):
            run_leaver_check([])
        linked.refresh_from_db()
        breakglass.refresh_from_db()
        self.assertFalse(linked.is_active)
        self.assertTrue(breakglass.is_active)  # not in Entra ID at all: left alone

    def test_a_rehire_gets_their_own_account_back(self):
        alex = User.objects.create_user("alex", EMAIL, sso_id=OID)
        Post.objects.create(author=alex, body="Before I left")
        with self.assertLogs("hub.security", "INFO"):
            run_leaver_check([])  # Alex leaves
        # IT turns the same Entra account back on. The hub waits for an admin to tick "Active".
        with self.assertLogs("hub.security", "WARNING"):
            self.assert_refused(self.sign_in())
        run_leaver_check([{"id": OID, "mail": EMAIL, "accountEnabled": True}])
        alex.refresh_from_db()
        self.assertFalse(alex.is_active)  # the leaver check never switches anyone back on by itself
        alex.is_active = True
        alex.save()
        self.sign_in()
        self.assertEqual(self.signed_in_user(), alex)
        alex.refresh_from_db()
        self.assertIsNone(alex.deactivated_at)  # the leaver retention clock has stopped
        self.assertTrue(Post.objects.filter(author=alex).exists())

        # Or IT made a new Entra account: a new permanent ID with the same email.
        self.client.logout()
        new_id = {"oid": "oid-new-account"}
        with self.assertLogs("hub.security", "WARNING") as logs:
            self.assert_refused(self.sign_in(**new_id))
        self.assertIn("linked to another sign-in", logs.records[0].details["reason"])
        admin = User.objects.create_superuser("admin", "admin@supreme.co.uk", policy_version=settings.POLICY_VERSION, sso_id="oid-admin")
        self.client.force_login(admin, backend="hub.auth.EmployeeOIDCBackend")
        with self.assertLogs("hub.security", "INFO"):
            self.client.post(reverse("admin:hub_user_changelist"), {"action": "unlink_sso", "_selected_action": [alex.pk]})
        self.client.logout()
        self.sign_in(**new_id)
        self.assertEqual(self.signed_in_user(), alex)
        alex.refresh_from_db()
        self.assertEqual(alex.sso_id, "oid-new-account")
        run_leaver_check([{"id": "oid-new-account", "mail": EMAIL, "accountEnabled": True}, {"id": "oid-admin", "accountEnabled": True}])
        alex.refresh_from_db()
        self.assertTrue(alex.is_active)


class SessionTests(TestCase):
    def setUp(self):
        self.alex = User.objects.create_user("alex", EMAIL, policy_version=settings.POLICY_VERSION)

    def test_signing_out_ends_the_session_on_the_server(self):
        self.client.force_login(self.alex)
        key = self.client.session.session_key
        self.assertRedirects(self.client.post(reverse("logout")), reverse("login"), fetch_redirect_response=False)
        self.assertFalse(Session.objects.filter(session_key=key).exists())
        copied = Client()  # someone who copied the cookie before
        copied.cookies[settings.SESSION_COOKIE_NAME] = key
        self.assertRedirects(copied.get(reverse("people")), f"{reverse('login')}?next=/people/", fetch_redirect_response=False)

    @override_settings(SESSION_COOKIE_AGE=12 * 60 * 60)  # Supreme's idle limit (config/settings.py)
    def test_the_idle_and_absolute_limits(self):
        start = timezone.now()

        def at(hours):
            return mock.patch("django.utils.timezone.now", return_value=start + timedelta(hours=hours))

        idle, busy = Client(), Client()
        for device in (idle, busy):
            with at(0):
                device.force_login(self.alex)
                self.assertEqual(device.get(reverse("people")).status_code, 200)
        # Idle: nothing renewed the session for 12 hours.
        with at(12.1), self.assertNoLogs("hub.security", "INFO"):
            self.assertRedirects(idle.get(reverse("people")), f"{reverse('login')}?next=/people/", fetch_redirect_response=False)
        # Absolute: renewed all day (as each 15-minute re-check does), still ended a day after signing in.
        for hours in (6, 12, 18, 23.9):
            with at(hours):
                session = busy.session
                session["oidc_id_token_expiration"] = time.time() + 15 * 60
                session.save()
                self.assertEqual(busy.get(reverse("people")).status_code, 200)
        key = busy.session.session_key
        with at(MAX_SESSION_AGE / 3600 + 0.1), self.assertLogs("hub.security", "INFO") as logs:
            response = busy.get(reverse("people"))
        self.assertRedirects(response, f"{reverse('login')}?next=/people/", fetch_redirect_response=False)
        self.assertEqual([r.getMessage() for r in logs.records], ["session_expired", "sign_out"])
        self.assertFalse(Session.objects.filter(session_key=key).exists())


class PasswordSignInTests(TestCase):
    def setUp(self):
        self.breakglass = User.objects.create_superuser(
            "breakglass", "breakglass@hub.invalid", "not-a-real-password", policy_version=settings.POLICY_VERSION
        )
        self.form = {"username": "breakglass", "password": "not-a-real-password"}

    def test_password_sign_in_is_off_unless_allow_password_login_is_set(self):
        self.assertNotIn(MODEL_BACKEND, production_settings()["AUTHENTICATION_BACKENDS"])
        self.assertIn(MODEL_BACKEND, production_settings(ALLOW_PASSWORD_LOGIN="1")["AUTHENTICATION_BACKENDS"])
        # Without single sign-on the password backend is there, but the sign-in page still refuses.
        with override_settings(ALLOW_PASSWORD_LOGIN=False):
            self.assertNotContains(self.client.get(reverse("login")), 'name="password"')
            self.assertEqual(self.client.post(reverse("login"), self.form).status_code, 403)
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_the_break_glass_sign_in_alerts_it(self):
        with override_settings(**sign_in_settings(ALLOW_PASSWORD_LOGIN="1"), ADMINS=[("IT", "it@supreme.co.uk")]):
            with self.assertLogs("hub.security", "INFO"):
                response = self.client.post(reverse("login"), self.form)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(int(self.client.session[SESSION_KEY]), self.breakglass.pk)
        self.assertEqual(mail.outbox[0].subject, "Staff hub: break-glass sign-in")
        self.assertIn("breakglass@hub.invalid", mail.outbox[0].body)
