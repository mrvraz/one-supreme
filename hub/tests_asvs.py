"""The fixes made while checking the hub against OWASP ASVS 4.0.3 Level 2 (docs/security/ASVS-L2.md).

Each test names the requirement it shows. The rest of the baseline is shown by the tests the ASVS file points to.
"""

import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .models import PushSubscription
from .tests import make_user

TEMP_MEDIA = tempfile.mkdtemp()
ENTRA = "https://login.microsoftonline.com/tenant-1/oauth2/v2.0"


@override_settings(MEDIA_ROOT=TEMP_MEDIA, ALLOW_PASSWORD_LOGIN=True)
class BaselineTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEMP_MEDIA, ignore_errors=True)

    def setUp(self):
        self.alice = make_user("alice")
        self.bob = make_user("bob")
        self.client.force_login(self.alice)

    def test_8_2_1_signed_in_pages_are_never_kept_by_the_browser_and_14_4_2_json_downloads(self):
        self.assertEqual(self.client.get(reverse("feed"))["Cache-Control"], "private, no-store")
        answer = self.client.get(reverse("people_suggest"), {"q": "bo"})
        self.assertEqual(answer.json()["people"][0]["name"], "Bob")
        self.assertEqual(answer["Cache-Control"], "private, no-store")
        self.assertEqual(answer["Content-Disposition"], 'attachment; filename="answer.json"')
        # Answers that choose their own caching keep it: photos for a day, the push worker always checked again.
        os.makedirs(os.path.join(TEMP_MEDIA, "avatars"), exist_ok=True)
        with open(os.path.join(TEMP_MEDIA, "avatars", "a.png"), "wb") as fh:
            fh.write(b"\x89PNG")
        photo = self.client.get("/media/avatars/a.png")
        self.assertEqual(photo["Cache-Control"], "private, max-age=86400")
        photo.close()
        worker = self.client.get(reverse("service_worker"))
        self.assertEqual(worker["Cache-Control"], "no-cache")
        worker.close()

    def test_7_2_2_refused_requests_are_logged_with_who_and_where(self):
        self.assertEqual(settings.MIDDLEWARE[-1], "hub.security.log_refusals")  # sees views and the form-token check
        browser = Client(enforce_csrf_checks=True)
        browser.force_login(self.alice)
        with self.assertLogs("hub.security", "WARNING") as logs:
            self.assertEqual(self.client.get(reverse("insights")).status_code, 403)  # needs "Can view usage figures"
            self.assertEqual(browser.post(reverse("feed"), {"body": "Hello"}).status_code, 403)  # no form token
        found = [(r.getMessage(), r.details["user"], r.details["path"], r.details["method"]) for r in logs.records]
        self.assertEqual(
            found, [("access_denied", "alice@example.com", "/insights/", "GET"), ("access_denied", "alice@example.com", "/", "POST")]
        )

    def test_2_1_1_passwords_need_at_least_12_characters(self):
        with self.assertRaises(ValidationError):
            validate_password("Kx7#mQ2!pL9")
        validate_password("Kx7#mQ2!pL9z")

    def test_13_2_5_push_sign_up_only_takes_json(self):
        data = json.dumps({"endpoint": "https://fcm.googleapis.com/fcm/send/abc", "keys": {"p256dh": "key", "auth": "secret"}})
        self.assertEqual(self.client.post(reverse("push_subscribe"), {"endpoint": "https://fcm.googleapis.com/x"}).status_code, 415)
        self.assertEqual(self.client.post(reverse("push_subscribe"), data, content_type="text/plain").status_code, 415)
        self.assertFalse(PushSubscription.objects.exists())
        self.assertEqual(self.client.post(reverse("push_subscribe"), data, content_type="application/json").status_code, 200)
        self.assertEqual(self.client.post(reverse("push_unsubscribe"), data, content_type="text/plain").status_code, 415)
        self.assertTrue(PushSubscription.objects.exists())

    @override_settings(
        OIDC_OP_LOGOUT_URL_METHOD="hub.auth.provider_logout_url",
        OIDC_OP_AUTHORIZATION_ENDPOINT=f"{ENTRA}/authorize",
        SITE_URL="https://hub.example.com",
    )
    def test_3_3_1_signing_out_also_signs_the_browser_out_of_microsoft(self):
        self.assertEqual(self.client.get(reverse("logout")).status_code, 405)  # a link can't sign anyone out
        with self.assertLogs("hub.security", "INFO") as logs:
            response = self.client.post(reverse("logout"))
        self.assertEqual(response["Location"], f"{ENTRA}/logout?post_logout_redirect_uri=https%3A%2F%2Fhub.example.com%2Flogin%2F")
        self.assertIn("sign_out", [r.getMessage() for r in logs.records])
        self.assertEqual(self.client.get(reverse("feed")).status_code, 302)  # and out of the hub
        self.client.force_login(self.alice)
        self.assertTrue(self.client.post("/oidc/logout/")["Location"].startswith(f"{ENTRA}/logout?"))  # the other address
        # Google Workspace has no sign-out page for other sites to use: back to the hub's sign-in page.
        self.client.force_login(self.alice)
        with self.settings(OIDC_OP_AUTHORIZATION_ENDPOINT="https://accounts.google.com/o/oauth2/v2/auth"):
            self.assertRedirects(self.client.post(reverse("logout")), reverse("login"), fetch_redirect_response=False)

    def test_without_single_sign_on_sign_out_goes_to_the_sign_in_page(self):
        self.assertRedirects(self.client.post(reverse("logout")), reverse("login"), fetch_redirect_response=False)
        self.assertEqual(self.client.get(reverse("feed")).status_code, 302)

    def test_3_4_4_production_session_cookie_is_host_only_and_single_sign_on_signs_out_of_microsoft(self):
        with tempfile.TemporaryDirectory() as data:
            production = {
                "DEBUG": "0", "SECRET_KEY": secrets.token_urlsafe(50), "DATA_DIR": data, "ALLOWED_HOSTS": "hub.example.com",
                "SITE_URL": "https://hub.example.com", "DJANGO_SETTINGS_MODULE": "config.settings",
                "OIDC_RP_CLIENT_ID": "test", "ALLOWED_EMAIL_DOMAINS": "example.com",
                "OIDC_OP_AUTHORIZATION_ENDPOINT": f"{ENTRA}/authorize", "OIDC_OP_TOKEN_ENDPOINT": f"{ENTRA}/token",
            }
            script = (
                "import django, json; django.setup(); from django.conf import settings as s; print(json.dumps("
                "[s.SESSION_COOKIE_NAME, s.SESSION_COOKIE_SECURE, s.SESSION_COOKIE_DOMAIN, s.SESSION_COOKIE_PATH, "
                "s.OIDC_OP_LOGOUT_URL_METHOD, s.MIDDLEWARE[-2:]]))"
            )
            result = subprocess.run(
                [sys.executable, "-c", script], cwd=settings.BASE_DIR, env={**os.environ, **production},
                capture_output=True, text=True, timeout=120,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        # __Host- only works with Secure, no Domain and Path=/, which these are. Refusals are logged inside the
        # single sign-on refresh, whose 403 to the chat's polling only asks it to renew the sign-in.
        refresh = "mozilla_django_oidc.middleware.SessionRefresh"
        self.assertEqual(
            json.loads(result.stdout.splitlines()[-1]),
            ["__Host-sessionid", True, None, "/", "hub.auth.provider_logout_url", [refresh, "hub.security.log_refusals"]],
        )
