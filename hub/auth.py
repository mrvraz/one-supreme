import logging

from django.conf import settings
from django.core.exceptions import SuspiciousOperation
from mozilla_django_oidc.auth import OIDCAuthenticationBackend

from .security import audit


class EmployeeOIDCBackend(OIDCAuthenticationBackend):
    """Single sign-on for company accounts only. Names and email stay in sync with the company directory."""

    def get_userinfo(self, access_token, id_token, payload):
        claims = super().get_userinfo(access_token, id_token, payload)
        # Microsoft's permanent user ID ("oid") is only in the signed ID token. It is also the user's ID in the
        # directory, which the leaver check uses. Other providers: their "sub" is permanent too.
        claims["sso_id"] = payload.get("oid") or claims.get("sub")
        return claims

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
        if not user.is_active:  # switched off in the admin: the sign-in view refuses it, this leaves a trace
            audit("sign_in_rejected", getattr(self, "request", None), level=logging.WARNING, email=user.email,
                  reason="account switched off")
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
