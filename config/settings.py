"""Settings come from environment variables (see .env.example). A local .env file is loaded if present."""

import os
import re
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

_env_file = BASE_DIR / ".env"
if _env_file.exists():
    for _line in _env_file.read_text(encoding="utf-8").splitlines():
        if "=" in _line and not _line.lstrip().startswith("#"):
            _key, _value = _line.split("=", 1)
            os.environ.setdefault(_key.strip(), _value.strip())


def env(name, default=""):
    return os.environ.get(name, default)


def env_bool(name, default=False):
    return env(name, str(default)).lower() in ("1", "true", "yes", "on")


def env_list(name, default=""):
    return [item.strip() for item in env(name, default).split(",") if item.strip()]


DEBUG = env_bool("DEBUG")
SECRET_KEY = env("SECRET_KEY") or ("dev-only-insecure-key" if DEBUG else "")
if not SECRET_KEY:
    raise ImproperlyConfigured("Set SECRET_KEY (or DEBUG=1 for local development).")

ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")
SITE_URL = env("SITE_URL", "http://localhost:8000").rstrip("/")

# Branding, so the same code can be sold to more than one company.
SITE_NAME = env("SITE_NAME", "Staff Hub")
# Optional. Empty keeps the blue of the Daylight looks; a company colour replaces it in both looks.
BRAND_COLOR = env("BRAND_COLOR")
if BRAND_COLOR and not re.fullmatch(r"#[0-9a-fA-F]{6}", BRAND_COLOR):
    raise ImproperlyConfigured("BRAND_COLOR must look like #4f46e5")
# Optional company logo: a folder in hub/static/hub/brand/ holding logo.png (dark, for the light look),
# logo-white.png (for the dark look) and icon.png (square, 512 px, solid background). Empty shows the name only.
BRAND = env("BRAND")
BRAND_FILES = ("logo.png", "logo-white.png", "icon.png")  # every page links all three: a missing one is a 500
if BRAND and not (
    re.fullmatch(r"[a-z0-9-]+", BRAND) and all((BASE_DIR / "hub/static/hub/brand" / BRAND / f).is_file() for f in BRAND_FILES)
):
    raise ImproperlyConfigured(f"BRAND={BRAND} needs logo.png, logo-white.png and icon.png in hub/static/hub/brand/{BRAND}/")
APP_VERSION = "2.0"

INSTALLED_APPS = [
    "hub",
    "chat",
    "library",
    "journeys",
    "jobs",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "mozilla_django_oidc",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "hub.security.security_headers",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # Every page needs a signed-in employee unless a view opts out with @login_not_required.
    "django.contrib.auth.middleware.LoginRequiredMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "hub.security.house_rules",
    "hub.security.presence",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "hub.context_processors.site",
            ],
        },
    },
]

DATA_DIR = Path(env("DATA_DIR", str(BASE_DIR / "data")))
DATA_DIR.mkdir(parents=True, exist_ok=True)
if env("DB_HOST"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "HOST": env("DB_HOST"),
            "PORT": env("DB_PORT", "5432"),
            "NAME": env("DB_NAME", "hub"),
            "USER": env("DB_USER", "hub"),
            "PASSWORD": env("DB_PASSWORD"),
            "CONN_MAX_AGE": 60,
        }
    }
else:
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": DATA_DIR / "db.sqlite3"}}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "hub.User"

# --- Sign-in -----------------------------------------------------------------
# Production: single sign-on with the company's Microsoft Entra ID (or Google) via OpenID Connect.
# Development and demos: ALLOW_PASSWORD_LOGIN=1 enables username/password accounts.
OIDC_RP_CLIENT_ID = env("OIDC_RP_CLIENT_ID")
OIDC_ENABLED = bool(OIDC_RP_CLIENT_ID)
ALLOW_PASSWORD_LOGIN = env_bool("ALLOW_PASSWORD_LOGIN")
ALLOWED_EMAIL_DOMAINS = [d.lower() for d in env_list("ALLOWED_EMAIL_DOMAINS")]

AUTHENTICATION_BACKENDS = []
if OIDC_ENABLED:
    # Guests in the company's directory have outside email addresses, so the domain list keeps them out.
    if not ALLOWED_EMAIL_DOMAINS:
        raise ImproperlyConfigured("Set ALLOWED_EMAIL_DOMAINS (e.g. supreme.co.uk) when single sign-on is on.")
    AUTHENTICATION_BACKENDS.append("hub.auth.EmployeeOIDCBackend")
    OIDC_RP_CLIENT_SECRET = env("OIDC_RP_CLIENT_SECRET")
    OIDC_OP_AUTHORIZATION_ENDPOINT = env("OIDC_OP_AUTHORIZATION_ENDPOINT")
    OIDC_OP_TOKEN_ENDPOINT = env("OIDC_OP_TOKEN_ENDPOINT")
    # Shared Microsoft endpoints accept people from any organisation, who can give themselves any email address.
    if re.search(r"/(common|organizations|consumers)/", OIDC_OP_AUTHORIZATION_ENDPOINT + OIDC_OP_TOKEN_ENDPOINT):
        raise ImproperlyConfigured("Use the company's own tenant ID in the sign-in addresses, not common/organizations.")
    OIDC_OP_USER_ENDPOINT = env("OIDC_OP_USER_ENDPOINT")
    OIDC_OP_JWKS_ENDPOINT = env("OIDC_OP_JWKS_ENDPOINT")
    OIDC_RP_SIGN_ALGO = "RS256"
    OIDC_RP_SCOPES = "openid email profile"
    OIDC_USE_PKCE = True
    LOGIN_REDIRECT_URL_FAILURE = "/login/?error=sso"
    # Re-check with the identity provider every 15 minutes, so people who leave lose access quickly.
    MIDDLEWARE.append("mozilla_django_oidc.middleware.SessionRefresh")
    OIDC_RENEW_ID_TOKEN_EXPIRY_SECONDS = 15 * 60
    OIDC_EXEMPT_URLS = [re.compile(r"^/media/"), "manifest", "icon"]
if ALLOW_PASSWORD_LOGIN or not OIDC_ENABLED:
    AUTHENTICATION_BACKENDS.append("django.contrib.auth.backends.ModelBackend")

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "feed"
LOGOUT_REDIRECT_URL = "login"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]

# --- Files ---------------------------------------------------------------------
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = DATA_DIR / "media"
# Uploads are only served to signed-in staff. Behind nginx, Django checks the login and nginx sends the file.
X_ACCEL_MEDIA = env_bool("X_ACCEL_MEDIA")
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        if DEBUG
        else "whitenoise.storage.CompressedManifestStaticFilesStorage"
    },
}
DATA_UPLOAD_MAX_NUMBER_FILES = 10

# --- Email (daily digest) ------------------------------------------------------
EMAIL_BACKEND = env(
    "EMAIL_BACKEND",
    "django.core.mail.backends.console.EmailBackend" if DEBUG else "django.core.mail.backends.smtp.EmailBackend",
)
EMAIL_HOST = env("EMAIL_HOST", "localhost")
EMAIL_PORT = int(env("EMAIL_PORT", "25"))
EMAIL_HOST_USER = env("EMAIL_HOST_USER")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", f"{SITE_NAME} <no-reply@localhost>")
# Alerts to IT (disk space, leaver check) go out from the same address; company relays refuse root@localhost.
SERVER_EMAIL = DEFAULT_FROM_EMAIL
EMAIL_SUBJECT_PREFIX = ""  # the subjects already say "Staff hub: ..."

# --- Security ------------------------------------------------------------------
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = not DEBUG
SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT")
SECURE_HSTS_SECONDS = int(env("SECURE_HSTS_SECONDS", "0"))
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
# Who gets alerts such as "the server's disk is nearly full". Comma-separated emails.
ADMINS = [(email, email) for email in env_list("ADMIN_EMAILS")]

# --- Push notifications (Web Push) ------------------------------------------------
# Create the key pair once with:  python manage.py vapid_keys   Leave empty to switch push off.
VAPID_PUBLIC_KEY = env("VAPID_PUBLIC_KEY")
VAPID_PRIVATE_KEY = env("VAPID_PRIVATE_KEY")
VAPID_CONTACT = env("VAPID_CONTACT", "mailto:it@example.com")  # who the push services can contact about problems

# --- Optional extras ----------------------------------------------------------------
# "See translation": the address of a LibreTranslate server (self-hosted keeps staff posts on the company's servers).
TRANSLATE_URL = env("TRANSLATE_URL")
TRANSLATE_API_KEY = env("TRANSLATE_API_KEY")
# Where the "Help" row on the About page goes: a web page or a mailto: address.
SUPPORT_URL = env("SUPPORT_URL")
# Chat messages older than this many days are removed. 0 keeps them.
CHAT_RETENTION_DAYS = int(env("CHAT_RETENTION_DAYS", "0"))

# --- Data protection -------------------------------------------------------------
# Bump POLICY_VERSION after editing hub/templates/hub/house_rules.html: everyone is asked to accept again.
POLICY_VERSION = env("POLICY_VERSION", "1")
PRIVACY_NOTICE_URL = env("PRIVACY_NOTICE_URL")
# Retention periods agreed with the company. 0 means keep (the default until the company decides).
POST_RETENTION_DAYS = int(env("POST_RETENTION_DAYS", "0"))
LEAVER_RETENTION_DAYS = int(env("LEAVER_RETENTION_DAYS", "0"))
NOTIFICATION_RETENTION_DAYS = int(env("NOTIFICATION_RETENTION_DAYS", "90"))

LANGUAGE_CODE = "en-gb"
TIME_ZONE = env("TIME_ZONE", "Europe/London")
USE_I18N = True
USE_TZ = True

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"json": {"()": "hub.security.JsonFormatter"}},
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
        "security": {"class": "logging.StreamHandler", "formatter": "json"},
    },
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
    "loggers": {
        # Sign-ins, failed sign-ins, deletions, limits hit, data exports: JSON lines for the company's SIEM.
        "hub.security": {"handlers": ["security"], "level": "INFO", "propagate": False},
        # Replaces Django's default handlers, which email ADMINS on every crash, with the request's form data
        # (a colleague's post) inside. Errors still reach the log; disk and leaver alerts call mail_admins directly.
        "django": {"level": "INFO"},
    },
}
