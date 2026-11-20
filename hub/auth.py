import logging
import re

import jwt
from django.conf import settings
from django.contrib.auth import logout
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import SuspiciousOperation
from django.utils import timezone
from mozilla_django_oidc.auth import OIDCAuthenticationBackend
from mozilla_django_oidc.views import OIDCAuthenticationCallbackView

from .security import audit


class EmployeeOIDCBackend(OIDCAuthenticationBackend):
    """Single sign-on for company accounts only. Names and email stay in sync with the company directory."""

    def get_userinfo(self, access_token, id_token, payload):
        claims = super().get_userinfo(access_token, id_token, payload)
        # Microsoft's permanent user ID ("oid") is only in the signed ID token. It is also the user's ID in the
        # directory, which the leaver check uses. Other providers: their "sub" is permanent too.
        claims["sso_id"] = payload.get("oid") or claims.get("sub")
        return claims

    def get_payload_data(self, token, key):
        """Check the ID token's signature and also what the library leaves out: that it was made for this app, by
        Supreme's own tenant, and is current. Microsoft signs every organisation's tokens with the same keys."""
        tenant = re.match(r"https://login\.microsoftonline\.com/([^/]+)/", self.OIDC_OP_TOKEN_ENDPOINT)
        try:
            return jwt.decode(
                token,
                key,
                algorithms=[self.OIDC_RP_SIGN_ALGO],
                audience=self.OIDC_RP_CLIENT_ID,
                issuer=f"https://login.microsoftonline.com/{tenant[1]}/v2.0" if tenant else None,
                leeway=60,  # a server clock a few seconds behind Microsoft's must not refuse a fresh token
                options={"require": ["exp", "iat"]},
            )
        except jwt.InvalidTokenError as exc:
            raise SuspiciousOperation(f"ID token refused: {exc}") from exc

    def verify_claims(self, claims):
        email = (claims.get("email") or "").lower()
        if "@" in email and email.rsplit("@", 1)[1] in settings.ALLOWED_EMAIL_DOMAINS:
            return True
        audit("sign_in_rejected", getattr(self, "request", None), level=logging.WARNING, email=email or "(none)")
        return False

    def filter_users_by_claims(self, claims):
        """Find the account by its permanent ID, so a changed email address doesn't create a second account."""
        if claims.get("sso_id"):
            linked = self.UserModel.objects.filter(sso_id=claims["sso_id"])
            if linked.exists():
                return linked
        # First sign-in with single sign-on: match by email, but never take over an account already linked.
        return self.UserModel.objects.filter(email__iexact=claims.get("email", ""), sso_id__isnull=True)

    def create_user(self, claims):
        email = claims.get("email", "")
        if self.UserModel.objects.filter(email__iexact=email).exists():
            # The directory re-created this person (new permanent ID, same email), e.g. a re-hire. Taking over the
            # old account automatically would be unsafe: an admin unlinks it ("Unlink single sign-on") instead.
            audit("sign_in_rejected", getattr(self, "request", None), level=logging.WARNING, email=email,
                  reason="email belongs to an account linked to another sign-in")
            raise SuspiciousOperation("Email belongs to an account linked to another sign-in")  # shows the sign-in error
        return self.update_user(super().create_user(claims), claims)

    def update_user(self, user, claims):
        if not user.is_active:
            # Switched off by an admin or the leaver check. Only an admin ticking "Active" lets them back in.
            audit("sign_in_rejected", getattr(self, "request", None), level=logging.WARNING, email=user.email,
                  reason="account switched off")
            raise SuspiciousOperation("Account switched off")  # shows the sign-in error
        first, last = claims.get("given_name", ""), claims.get("family_name", "")
        if not (first or last) and claims.get("name"):
            first, _, last = claims["name"].partition(" ")
        user.first_name, user.last_name = first[:150], last[:150]
        user.sso_id = claims.get("sso_id") or user.sso_id
        email = claims.get("email", "")
        if email and not self.UserModel.objects.filter(email__iexact=email).exclude(pk=user.pk).exists():
            user.email = email  # follows a name change in the directory
        user.save(update_fields=["first_name", "last_name", "sso_id", "email"])
        return user

    def get_user(self, user_id):
        # Accounts switched off in the admin are signed out on their next request.
        user = super().get_user(user_id)
        return user if user and user.is_active else None


class CallbackView(OIDCAuthenticationCallbackView):
    """Where Microsoft sends people back. Unlike the library's view, every failure signs the person out.

    The library keeps someone signed in when their 15-minute re-check comes back refused (say their email is now
    outside ALLOWED_EMAIL_DOMAINS), and answers a wrong state, nonce or token with a bare error page."""

    def get(self, request):
        try:
            return super().get(request)
        except SuspiciousOperation as exc:
            audit("sign_in_rejected", request, level=logging.WARNING, reason=str(exc))
            return self.login_failure()

    def login_failure(self):
        logout(self.request)
        return super().login_failure()


SIGNED_IN_AT = "signed_in_at"
MAX_SESSION_AGE = 24 * 60 * 60  # the absolute limit; settings.SESSION_COOKIE_AGE is the idle one


def session_limit(get_response):
    """Everyone signs in afresh a day after they last did, however busy they are, so a copied session cookie
    stops working. The 15-minute re-check with Entra ID keeps the same session going, so it can't do this."""

    def middleware(request):
        if request.user.is_authenticated:
            now = timezone.now().timestamp()
            if now - request.session.setdefault(SIGNED_IN_AT, now) > MAX_SESSION_AGE:
                audit("session_expired", request)
                logout(request)
                return redirect_to_login(request.get_full_path())
        return get_response(request)

    return middleware
