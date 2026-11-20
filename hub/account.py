"""The Menu tab, notifications, settings, search, the About pages, push sign-up, insights and data export."""

import json
import os
import tempfile
import zipfile
from datetime import timedelta
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_not_required
from django.contrib.staticfiles import finders
from django.core.exceptions import PermissionDenied
from django.db.models import Count
from django.http import FileResponse, HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import plugins
from .forms import AppearanceForm, NotificationForm, PrivacyForm, ReminderForm
from .models import Comment, Community, Event, FeatureNote, Notification, Post, PushSubscription, User, matching, notify
from .publishing import post_audience
from .security import audit
from .views import paginate, safe_redirect, visible_events

# --- Menu --------------------------------------------------------------------------

# (position, label, url name, icon). The other apps add their rows through plugins.MENU.
HUB_MENU = [
    (10, "Scheduled posts", "scheduled", "clock"),
    (60, "Events", "events", "calendar"),
    (80, "Organisation", "organisation", "building"),
    (90, "People", "people", "people"),
    (100, "Groups", "communities", "groups"),
    (110, "Birthdays", "birthdays", "cake"),
]


def unseen_notes(user):
    notes = FeatureNote.objects.filter(published_at__lte=timezone.now())
    return notes.filter(published_at__gt=user.whats_new_seen_at).count() if user.whats_new_seen_at else notes.count()


def menu(request):
    context = {"nav": "menu", "rows": sorted(HUB_MENU + plugins.MENU)}
    return render(request, "hub/menu.html", context)


@require_POST
def dnd_toggle(request):
    user = request.user
    user.dnd_on = not user.dnd_on
    user.save(update_fields=["dnd_on"])
    messages.success(request, "Do not disturb is on. No push or email until you turn it off." if user.dnd_on else "Do not disturb is off.")
    return safe_redirect(request, request.META.get("HTTP_REFERER", ""), reverse("menu"))


# --- Notifications -------------------------------------------------------------------


def _my_alerts(user):
    return user.notifications.exclude(category="messages")  # chat has its own tab and badge


def notifications(request):
    show = "unread" if request.GET.get("show") == "unread" else "all"
    items = _my_alerts(request.user).select_related("actor", "invite", "invite__community")
    if show == "unread":
        items = items.filter(read_at__isnull=True)
    return render(request, "hub/notifications.html", {"nav": "alerts", "page": paginate(request, items, 40), "show": show})


def notification_open(request, pk):
    """Mark one notification read and go to what it is about."""
    item = get_object_or_404(Notification, pk=pk, recipient=request.user)
    if item.read_at is None:
        item.read_at = timezone.now()
        item.save(update_fields=["read_at"])
    return safe_redirect(request, item.url, reverse("notifications"))


@require_POST
def notifications_read_all(request):
    _my_alerts(request.user).filter(read_at__isnull=True).update(read_at=timezone.now())
    return redirect("notifications")


# --- Settings ------------------------------------------------------------------------

TRANSLATE_LANGUAGES = [
    ("en", "English"), ("pl", "Polish"), ("ro", "Romanian"), ("lt", "Lithuanian"), ("lv", "Latvian"), ("bg", "Bulgarian"),
    ("hu", "Hungarian"), ("pt", "Portuguese"), ("es", "Spanish"), ("uk", "Ukrainian"), ("ru", "Russian"), ("ar", "Arabic"),
    ("hi", "Hindi"), ("ur", "Urdu"), ("fr", "French"), ("de", "German"), ("it", "Italian"), ("tr", "Turkish"),
    ("cs", "Czech"), ("sk", "Slovak"),
]


def settings_home(request):
    return render(request, "hub/settings.html", {"nav": "menu"})


def settings_notifications(request):
    form = NotificationForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Notification settings saved.")
        return redirect("settings_notifications")
    context = {
        "nav": "menu", "form": form,
        "vapid_key": settings.VAPID_PUBLIC_KEY if settings.VAPID_PRIVATE_KEY else "",
        "devices": request.user.push_subscriptions.count(),
    }
    return render(request, "hub/settings_notifications.html", context)


def settings_reminders(request):
    form = ReminderForm(request.POST or None, initial={"reminders": request.user.event_reminders})
    if request.method == "POST" and form.is_valid():
        request.user.event_reminders = form.cleaned_data["reminders"]
        request.user.save(update_fields=["event_reminders"])
        messages.success(request, "Reminder settings saved.")
        return redirect("settings_reminders")
    return render(request, "hub/settings_form.html", {
        "nav": "menu", "form": form, "title": "Event reminders",
        "intro": "When should we remind you about events you're going to? You can change this for a single event on its page.",
    })


def settings_privacy(request):
    form = PrivacyForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Privacy settings saved.")
        return redirect("settings_privacy")
    return render(request, "hub/settings_form.html", {
        "nav": "menu", "form": form, "title": "Privacy and security", "privacy": True,
        "intro": "Your birthday is only shown if you add it to your profile.",
    })


def settings_appearance(request):
    user = request.user
    if request.method == "POST":
        form = AppearanceForm(request.POST, instance=user)
        if "look" in request.POST and form.is_valid():
            form.save()
        if settings.TRANSLATE_URL and request.POST.get("language") in dict(TRANSLATE_LANGUAGES):
            user.language = request.POST["language"]
            user.save(update_fields=["language"])
        messages.success(request, "Saved.")
        return redirect("settings_appearance")
    context = {"nav": "menu", "looks": User.LOOKS, "languages": TRANSLATE_LANGUAGES if settings.TRANSLATE_URL else []}
    return render(request, "hub/settings_appearance.html", context)


@require_POST
def look_switch(request):
    """The sun/moon button in the top bar: save Daylight or Daylight Dark and go back to the same page."""
    look = request.POST.get("look")
    if look not in ("daylight", "daylight-dark"):
        return HttpResponseBadRequest("Unknown look.")
    request.user.look = look
    request.user.save(update_fields=["look"])
    if request.headers.get("X-Fragment"):  # app.js already switched the page; it only needs the choice saved
        return HttpResponse(status=204)
    return safe_redirect(request, request.META.get("HTTP_REFERER", ""), reverse("feed"))


# --- About ---------------------------------------------------------------------------

LICENCES = [
    ("Django", "BSD 3-Clause"), ("Pillow", "MIT-CMU (HPND)"), ("psycopg", "LGPL 3.0"), ("Gunicorn", "MIT"),
    ("WhiteNoise", "MIT"), ("mozilla-django-oidc", "MPL 2.0"), ("Requests", "Apache 2.0"), ("http-ece", "MIT"),
    ("py-vapid", "MPL 2.0"), ("cryptography", "Apache 2.0 or BSD"), ("FFmpeg", "LGPL 2.1 or later"),
    ("PostgreSQL", "PostgreSQL Licence"), ("nginx", "BSD 2-Clause"), ("Lucide and Feather icons", "ISC and MIT"),
]


def about(request):
    context = {
        "nav": "menu", "version": settings.APP_VERSION, "support_url": settings.SUPPORT_URL,
        "privacy_url": settings.PRIVACY_NOTICE_URL, "unseen_notes": unseen_notes(request.user),
    }
    return render(request, "hub/about.html", context)


def whats_new(request):
    notes = list(FeatureNote.objects.filter(published_at__lte=timezone.now()))
    seen = request.user.whats_new_seen_at
    for note in notes:
        note.is_new = seen is None or note.published_at > seen
    User.objects.filter(pk=request.user.pk).update(whats_new_seen_at=timezone.now())
    return render(request, "hub/whats_new.html", {"nav": "menu", "notes": notes})


def licences(request):
    return render(request, "hub/licences.html", {"nav": "menu", "licences": LICENCES})


# --- Search --------------------------------------------------------------------------


def _hub_results(user, q, limit):
    """Search hub's own sections. Returns [(section label, [(title, url, subtitle)…])…]."""
    staff = matching(User.objects.filter(is_active=True), q, "first_name", "last_name", "job_title", "department")
    posts = matching(Post.objects.visible().viewable_by(user), q, "title", "body").select_related("author")
    posts = posts.exclude(kind=Post.EVENT).order_by("-created_at")
    groups = matching(Community.objects.all(), q, "name", "description")
    events = matching(visible_events(user), q, "title", "location").order_by("-starts_at")

    def when(moment):
        return timezone.localtime(moment).strftime("%d %b %Y")

    return [
        ("People", [(str(p), p.get_absolute_url(), p.job_title or p.department) for p in staff[:limit]]),
        ("News", [(str(p), p.get_absolute_url(), f"{p.author} · {when(p.created_at)}") for p in posts.filter(kind=Post.NEWS)[:limit]]),
        ("Posts", [(str(p), p.get_absolute_url(), f"{p.author} · {when(p.created_at)}") for p in posts.exclude(kind=Post.NEWS)[:limit]]),
        ("Groups and teams", [(g.name, g.get_absolute_url(), g.type_label) for g in groups[:limit]]),
        ("Events", [(e.title, e.get_absolute_url(), when(e.starts_at)) for e in events[:limit]]),
    ]


def _results(user, q, limit):
    sections = _hub_results(user, q, limit) + [provider(user, q, limit) for provider in plugins.SEARCH_PROVIDERS]
    return [(label, rows) for label, rows in sections if rows]


def search(request):
    q = request.GET.get("q", "").strip()[:100]
    sections = _results(request.user, q, 20) if len(q) >= 2 else []
    return render(request, "hub/search.html", {"q": q, "sections": sections})


def search_suggest(request):
    """The best few matches while someone is still typing."""
    q = request.GET.get("q", "").strip()[:100]
    found = []
    if len(q) >= 2:
        for label, rows in _results(request.user, q, 3):
            found += [{"section": label, "title": title, "url": url, "detail": detail} for title, url, detail in rows]
    return JsonResponse({"results": found[:10]})


# --- Push notifications ----------------------------------------------------------------

# The server later sends to the address the browser gives us, so only real push services are accepted.
PUSH_HOSTS = ("fcm.googleapis.com", "push.apple.com", "push.services.mozilla.com", "notify.windows.com")


@login_not_required
def service_worker(request):
    """The small script that shows push notifications. Served from the top of the site so it covers every page."""
    response = FileResponse(open(finders.find("hub/sw.js"), "rb"), content_type="text/javascript")
    response["Cache-Control"] = "no-cache"
    return response


@require_POST
def push_subscribe(request):
    if request.content_type != "application/json":  # app.js always sends JSON; anything else isn't from the hub
        return HttpResponse("Send the subscription as JSON.", status=415)
    try:
        data = json.loads(request.body)
        endpoint, p256dh, auth = data["endpoint"], data["keys"]["p256dh"], data["keys"]["auth"]
        target = urlsplit(endpoint)
    except (ValueError, KeyError, TypeError):
        return HttpResponseBadRequest("That isn't a push subscription.")
    host = target.hostname or ""
    known = any(host == allowed or host.endswith("." + allowed) for allowed in PUSH_HOSTS)
    if target.scheme != "https" or not known or len(endpoint) > 600 or len(p256dh) > 200 or len(auth) > 100:
        return HttpResponseBadRequest("That isn't a push service we know.")
    PushSubscription.objects.update_or_create(
        endpoint=endpoint,
        defaults={"user": request.user, "p256dh": p256dh, "auth": auth, "device": request.headers.get("User-Agent", "")[:200]},
    )
    extra = request.user.push_subscriptions.order_by("-created_at").values_list("pk", flat=True)[10:]
    PushSubscription.objects.filter(pk__in=list(extra)).delete()  # keep a person's ten newest devices
    audit("push_enabled", request)
    return JsonResponse({"ok": True})


@require_POST
def push_unsubscribe(request):
    if request.content_type != "application/json":
        return HttpResponse("Send the subscription as JSON.", status=415)
    try:
        endpoint = json.loads(request.body)["endpoint"]
    except (ValueError, KeyError, TypeError):
        return HttpResponseBadRequest("That isn't a push subscription.")
    request.user.push_subscriptions.filter(endpoint=endpoint).delete()
    return JsonResponse({"ok": True})


@require_POST
def push_test(request):
    notify([request.user], None, "Test: push notifications are working", reverse("settings_notifications"))
    messages.success(request, "A test notification is on its way. It can take up to a minute.")
    return redirect("settings_notifications")


# --- Insights for admins ---------------------------------------------------------------


def insights(request):
    if not request.user.has_perm("hub.view_insights"):
        raise PermissionDenied
    now = timezone.now()
    week, month = now - timedelta(days=7), now - timedelta(days=30)
    staff = User.objects.filter(is_active=True)
    live = Post.objects.visible()
    figures = [
        ("People with an account", staff.count()),
        ("Active in the last 7 days", staff.filter(last_seen__gte=week).count()),
        ("Active in the last 30 days", staff.filter(last_seen__gte=month).count()),
        ("Posts in the last 30 days", live.filter(created_at__gte=month).exclude(kind=Post.EVENT).count()),
        ("Comments in the last 30 days", Comment.objects.visible().filter(created_at__gte=month).count()),
        ("Events coming up", Event.objects.filter(starts_at__gte=now).count()),
        ("People with push switched on", staff.filter(push_subscriptions__isnull=False).distinct().count()),
    ]
    news = []
    for item in live.filter(kind=Post.NEWS).order_by("-created_at")[:10]:
        audience = post_audience(item).exclude(pk=item.author_id).count()
        read = item.reads.exclude(user=item.author_id).count()
        news.append((item, read, audience, round(100 * read / audience) if audience else 0))
    popular = live.filter(created_at__gte=month).annotate(n=Count("reactions")).filter(n__gt=0).order_by("-n")[:5]
    return render(request, "hub/insights.html", {"nav": "menu", "figures": figures, "news": news, "popular": popular})


# --- Data protection ---------------------------------------------------------------------


def house_rules(request):
    """The rules and data notice everyone accepts before using the hub (see security.house_rules)."""
    accepted = request.user.policy_version == settings.POLICY_VERSION
    if request.method == "POST":
        request.user.policy_version = settings.POLICY_VERSION
        request.user.save(update_fields=["policy_version"])
        audit("house_rules_accepted", request, version=settings.POLICY_VERSION)
        return safe_redirect(request, request.POST.get("next", ""), reverse("feed"))
    context = {"accepted": accepted, "next": request.GET.get("next", ""), "PRIVACY_NOTICE_URL": settings.PRIVACY_NOTICE_URL}
    return render(request, "hub/house_rules.html", context)


def export_my_data(request):
    """A zip of everything this person has put into the hub, so they can see what's held (subject access)."""
    user = request.user
    posts = Post.objects.filter(author=user).select_related("community").prefetch_related("attachments", "audiences")
    profile_fields = [
        "username", "email", "first_name", "last_name", "job_title", "department", "pronouns", "languages", "phone", "bio",
        "birthday", "start_date", "share_email", "show_presence", "look", "language", "email_digest", "notify_prefs",
        "dnd_on", "dnd_from", "dnd_to", "dnd_weekends", "event_reminders", "date_joined", "last_login", "last_seen", "policy_version",
    ]
    data = {
        "profile": {field: getattr(user, field) for field in profile_fields},
        "groups_and_units": list(user.communities.values_list("name", flat=True)),
        "posts": [
            {
                "type": p.get_kind_display(), "created_at": p.created_at, "title": p.title, "text": p.body,
                "sent_to": [str(p.community)] if p.community else [a.name for a in p.audiences.all()] or ["Everyone"],
                "draft": p.is_draft, "hidden_by_moderator": p.is_hidden, "deleted_at": p.deleted_at,
                "files": [f"files/{os.path.basename(a.file.name)}" for a in p.attachments.all()],
            }
            for p in posts
        ],
        "comments": list(user.comments.values("created_at", "post_id", "body", "is_hidden", "deleted_at")),
        "reactions": list(user.reactions.values("post_id", "kind")) + list(user.comment_reactions.values("comment_id", "kind")),
        "poll_votes": list(user.poll_votes.values("post_id", "option__text")),
        "news_read": list(user.post_reads.values("post_id", "read_at", "acknowledged_at")),
        "events_organised": list(user.events_created.values("title", "starts_at", "location", "description")),
        "rsvps": list(user.rsvps.values("event__title", "status")),
        "notifications": list(user.notifications.values("created_at", "message", "read_at")),
        "push_devices": list(user.push_subscriptions.values("device", "created_at")),
    }
    files = [a.file.path for p in posts for a in p.attachments.all()]
    files += [p.cover.path for p in posts if p.cover]
    files += [c.image.path for c in user.comments.exclude(image="")]
    files += [picture.path for picture in (user.avatar, user.cover) if picture]
    for exporter in plugins.EXPORTERS:
        key, section, paths = exporter(user)
        data[key] = section
        files += paths
    buffer = tempfile.SpooledTemporaryFile(max_size=50 * 1024 * 1024)
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("my-data.json", json.dumps(data, indent=2, default=str))
        for path in files:
            if os.path.isfile(path):  # photos and videos are already compressed
                archive.write(path, f"files/{os.path.basename(path)}", compress_type=zipfile.ZIP_STORED)
    buffer.seek(0)
    audit("data_exported", request)
    return FileResponse(buffer, as_attachment=True, filename="my-hub-data.zip")
