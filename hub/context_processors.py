from datetime import timedelta

from django.conf import settings
from django.templatetags.static import static
from django.utils import timezone

from . import plugins
from .models import Post, Reaction, ReactionKind


def brand_file(name):
    """Address of one of the company's logo files (settings.BRAND), or "" when no logo is set."""
    return static(f"hub/brand/{settings.BRAND}/{name}") if settings.BRAND else ""


def site(request):
    """Values every page needs: branding, the chosen look, and the red badges on the tabs."""
    user = getattr(request, "user", None)
    signed_in = user is not None and user.is_authenticated
    look_pref = user.look if signed_in else "auto"
    context = {
        "SITE_NAME": settings.SITE_NAME,
        "BRAND_COLOR": settings.BRAND_COLOR,
        "BRAND_ICON": brand_file("icon.png"),
        "BRAND_LOGO": brand_file("logo.png"),
        "BRAND_LOGO_WHITE": brand_file("logo-white.png"),
        "OIDC_ENABLED": settings.OIDC_ENABLED,
        "ALLOW_PASSWORD_LOGIN": settings.ALLOW_PASSWORD_LOGIN,
        "LOOK_PREF": look_pref,
        "LOOK": "daylight" if look_pref == "auto" else look_pref,  # theme.js switches "auto" to dark on dark devices
        "unread_count": 0,
        "unread_news": 0,
        "nav_badges": {},
        "TRANSLATE_ENABLED": bool(settings.TRANSLATE_URL),
        "REACTION_CHOICES": ReactionKind.choices,
        "REACTION_EMOJI": Reaction.EMOJI,
        "REACTION_LABELS": dict(ReactionKind.choices),
    }
    if signed_in:
        # Chat has its own badge, so chat alerts are left out of the Notifications count.
        context["unread_count"] = user.notifications.filter(read_at__isnull=True).exclude(category="messages").count()
        recent = timezone.now() - timedelta(days=90)
        context["unread_news"] = (
            Post.objects.visible().in_feed_of(user).filter(kind=Post.NEWS, created_at__gte=recent)
            .exclude(reads__user=user).exclude(author=user).count()
        )
        context["nav_badges"] = {tab: count(user) for tab, count in plugins.NAV_BADGES.items()}
    return context
