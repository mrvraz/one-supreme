"""Pages for the feed, posts, people, groups, the organisation and events.

News lives in news.py; the menu, notifications, settings, search and "about" pages live in account.py.
"""

import mimetypes
import os
from collections import Counter, defaultdict
from datetime import timedelta
from datetime import timezone as dt_timezone
from urllib.parse import quote

import requests
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_not_required
from django.core.exceptions import PermissionDenied, SuspiciousFileOperation
from django.core.files.storage import default_storage
from django.core.paginator import Paginator
from django.db.models import Count, Prefetch, Q
from django.http import FileResponse, Http404, HttpResponse, HttpResponseBadRequest, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils._os import safe_join
from django.utils.html import escape
from django.utils.http import content_disposition_header, url_has_allowed_host_and_scheme
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from . import plugins, richtext
from .context_processors import brand_file
from .forms import CommentForm, CommunityForm, EventForm, PostEditForm, PostForm, ProfileForm, ReminderForm, ReportForm
from .models import (
    DELETED_KEEP_DAYS,
    RSVP,
    Attachment,
    Comment,
    CommentReaction,
    Community,
    Event,
    GroupInvite,
    Notification,
    PollOption,
    PollVote,
    Post,
    PostFollow,
    PostRead,
    Reaction,
    ReactionKind,
    ReminderSent,
    Report,
    User,
    matching,
    next_occurrence,
    notify,
)
from .publishing import announce, post_audience, set_mentions
from .security import LIMIT_MESSAGE, audit, over_limit, record_change

# --- Sign-in and app shell -------------------------------------------------------


class LoginView(auth_views.LoginView):
    template_name = "hub/login.html"
    redirect_authenticated_user = True

    def post(self, request, *args, **kwargs):
        if not settings.ALLOW_PASSWORD_LOGIN:
            return HttpResponseForbidden("Password sign-in is turned off. Sign in with your work account.")
        return super().post(request, *args, **kwargs)


@login_not_required
def manifest(request):
    """Lets staff add the site to their phone's home screen like an app."""
    return JsonResponse(
        {
            "name": settings.SITE_NAME,
            "short_name": settings.SITE_NAME,
            "start_url": "/",
            "display": "standalone",
            "background_color": "#F2F2F7",
            "theme_color": "#F2F2F7",
            "icons": [{"src": brand_file("icon.png"), "sizes": "512x512", "type": "image/png"}] if settings.BRAND
            else [{"src": reverse("icon"), "sizes": "any", "type": "image/svg+xml"}],
        },
        content_type="application/manifest+json",
    )


@login_not_required
def icon(request):
    if settings.BRAND:  # push notifications and older pages ask for /icon.svg
        return redirect(brand_file("icon.png"))
    letter = escape(settings.SITE_NAME[:1].upper())
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        f'<rect width="100" height="100" rx="22" fill="{settings.BRAND_COLOR or "#007AFF"}"/>'
        '<text x="50" y="68" font-family="system-ui,sans-serif" font-size="56" font-weight="700" '
        f'fill="#fff" text-anchor="middle">{letter}</text></svg>'
    )
    return HttpResponse(svg, content_type="image/svg+xml")


def can_open_post(user, post_id):
    """May this person open this post and its files? Authors can always open their own drafts and scheduled posts."""
    if user.has_perm("hub.change_post"):
        return True  # moderators review hidden and deleted posts too
    own = Post.objects.filter(pk=post_id, author=user, is_hidden=False, deleted_at__isnull=True)
    return own.exists() or Post.objects.visible().viewable_by(user).filter(pk=post_id).exists()


def _guard_post_file(user, name):
    attachment = Attachment.objects.filter(file=name).first()
    return attachment is not None and can_open_post(user, attachment.post_id)


def _guard_cover(user, name):
    if not name.startswith("covers/news/"):
        return True  # profile and group covers are shown in lists every colleague can see
    post = Post.objects.filter(cover=name).first()
    return post is not None and can_open_post(user, post.pk)


def _guard_comment_image(user, name):
    comment = Comment.objects.filter(image=name).first()
    if comment is None or not can_open_post(user, comment.post_id):
        return False
    return (not comment.is_hidden and comment.deleted_at is None) or user.has_perm("hub.change_comment")


plugins.MEDIA_GUARDS.update(
    {"avatars": lambda user, name: True, "covers": _guard_cover, "posts": _guard_post_file, "comments": _guard_comment_image}
)
# Every colleague sees these, so browsers may keep them for a day. Any other file may be private to some people.
SHARED_MEDIA = ("avatars/", "covers/people/", "covers/groups/")


def media(request, path):
    """Uploaded files, for signed-in staff only, and only the files each person may see.

    The top folder of the file picks a guard from plugins.MEDIA_GUARDS. A guard returns False (no),
    True (yes) or a file name to offer as a download. Folders without a guard are never served.
    """
    try:
        full_path = safe_join(settings.MEDIA_ROOT, path)
    except SuspiciousFileOperation:
        raise Http404
    if not os.path.isfile(full_path):
        raise Http404
    # The real file name, after resolving tricks like "avatars/../posts/…" that would pick the wrong guard.
    name = os.path.relpath(full_path, settings.MEDIA_ROOT).replace(os.sep, "/")
    guard = plugins.MEDIA_GUARDS.get(name.split("/", 1)[0])
    allowed = guard(request.user, name) if guard else False
    if not allowed:
        raise Http404
    content_type = mimetypes.guess_type(full_path)[0] or "application/octet-stream"
    if settings.X_ACCEL_MEDIA:
        response = HttpResponse(content_type=content_type)
        response["X-Accel-Redirect"] = "/protected-media/" + quote(name)  # nginx sends the file, with video seeking
    else:
        response = FileResponse(open(full_path, "rb"), content_type=content_type)
    # Only pictures, video and sound open in the browser. Everything else downloads, so a document can never run as a page.
    shown_inline = content_type.split("/")[0] in ("image", "video", "audio") and content_type != "image/svg+xml"
    if not shown_inline or isinstance(allowed, str):
        filename = allowed if isinstance(allowed, str) else os.path.basename(name)
        response["Content-Disposition"] = content_disposition_header(as_attachment=not shown_inline, filename=filename)
    # Private files are never kept: on a shared device the next person could open them from the history.
    response["Cache-Control"] = "private, max-age=86400" if name.startswith(SHARED_MEDIA) else "private, no-store"
    return response


# --- Helpers ---------------------------------------------------------------------


def post_queryset(live=True):
    """Posts with everything a post card shows. live=False also includes drafts and scheduled posts."""
    posts = Post.objects.visible() if live else Post.objects.filter(is_hidden=False, deleted_at__isnull=True)
    comments = Comment.objects.visible().select_related("author").prefetch_related("reactions", "mentions")
    return posts.select_related("author", "community", "event").prefetch_related(
        "attachments", "reactions", "audiences", "mentions", "options", Prefetch("comments", queryset=comments)
    )


def get_post(request, pk):
    """A post the person may open, including their own drafts and scheduled posts. 404 otherwise."""
    post = post_queryset().viewable_by(request.user).filter(pk=pk).first()
    if post is None:
        post = post_queryset(live=False).filter(pk=pk, author=request.user).first()
    if post is None:
        raise Http404
    return post


def visible_events(user):
    return (
        Event.objects.filter(Q(community__isnull=True) | Q(community__in=user.communities.all()))
        .select_related("community")
        .annotate(going=Count("rsvps", filter=Q(rsvps__status=RSVP.Status.GOING)))
        .order_by("starts_at")
    )


def _my_reaction(reactions, user):
    return next((r.kind for r in reactions if r.user_id == user.pk), None)


def decorate(posts, user):
    """Attach what the post card template needs: reactions, comments with replies, poll results, read state."""
    posts = list(posts)
    moderator = user.has_perm("hub.change_post")
    managed = set(user.communities_managed.values_list("pk", flat=True))
    following = set(PostFollow.objects.filter(post__in=posts, user=user).values_list("post_id", flat=True))
    reads = dict(PostRead.objects.filter(post__in=posts, user=user).values_list("post_id", "acknowledged_at"))
    polls = [p for p in posts if p.kind == Post.POLL]
    tallies = Counter(PollVote.objects.filter(post__in=polls).values_list("option_id", flat=True)) if polls else {}
    my_votes = dict(PollVote.objects.filter(post__in=polls, user=user).values_list("post_id", "option_id")) if polls else {}

    for post in posts:
        reactions = list(post.reactions.all())
        post.my_reaction = _my_reaction(reactions, user)
        post.reaction_total = len(reactions)
        post.reaction_emojis = "".join(Reaction.EMOJI[kind] for kind, _n in Counter(r.kind for r in reactions).most_common(3))

        comments = list(post.comments.all())
        replies = defaultdict(list)
        for comment in comments:
            comment_reactions = list(comment.reactions.all())
            comment.my_reaction = _my_reaction(comment_reactions, user)
            comment.reaction_total = len(comment_reactions)
            if comment.parent_id:
                replies[comment.parent_id].append(comment)
        post.comment_list = [c for c in comments if c.parent_id is None]
        for comment in post.comment_list:
            comment.reply_list = replies[comment.pk]
        post.comment_total = len(comments)

        post.user_can_pin = moderator or post.community_id in managed
        post.is_followed = post.pk in following
        post.is_read = post.pk in reads or post.author_id == user.pk
        post.is_acknowledged = bool(reads.get(post.pk))
        post.audience_names = [a.name for a in post.audiences.all()]
        if post.kind == Post.POLL:
            options = list(post.options.all())
            total = sum(tallies[o.pk] for o in options)
            for option in options:
                option.count = tallies[option.pk]
                option.percent = round(100 * option.count / total) if total else 0
            post.poll_options, post.poll_total, post.my_vote = options, total, my_votes.get(post.pk)
            post.show_results = post.my_vote is not None or not post.poll_open or post.author_id == user.pk
    return posts


def as_id(value):
    """A record id from a form or link, or 0 (matches nothing) when it isn't a number: ?unit=abc must not crash."""
    return int(value) if value and value.isdecimal() else 0


def paginate(request, queryset, per_page=20):
    return Paginator(queryset, per_page).get_page(request.GET.get("page"))


def safe_redirect(request, url, default):
    """Redirect to url if it stays on this site, otherwise to default."""
    if not url_has_allowed_host_and_scheme(url, {request.get_host()}, require_https=request.is_secure()):
        url = default
    return redirect(url)


def post_changed(request, post_pk):
    """After a reaction, vote or comment: return the refreshed post card to the page script, or reload the page."""
    if request.headers.get("X-Fragment"):
        post = get_post(request, post_pk)
        context = {"post": decorate([post], request.user)[0], "full": request.POST.get("full") == "1"}
        return render(request, "hub/_post.html", context)
    anchor = f"#post-{post_pk}"
    back = request.META.get("HTTP_REFERER", "").split("#")[0]
    return safe_redirect(request, back and back + anchor, reverse("post_detail", args=[post_pk]) + anchor)


def refuse(request, text, status=400):
    """Tell the page script (or the page) that an action wasn't accepted."""
    if request.headers.get("X-Fragment"):
        return HttpResponse(text, status=status)
    messages.error(request, text)
    return safe_redirect(request, request.META.get("HTTP_REFERER", ""), reverse("feed"))


def handle_composer(request, community=None):
    """Return (form, response). response is a redirect once a post is published or scheduled."""
    if request.method != "POST":
        return PostForm(user=request.user, community=community), None
    form = PostForm(request.POST, request.FILES, user=request.user, community=community)
    if not form.is_valid():
        return form, None
    post = form.save()
    set_mentions(post)
    if post.is_scheduled:
        when = timezone.localtime(post.created_at).strftime("%d %b at %H:%M")
        messages.success(request, f"Scheduled for {when}. You can change it under Menu, Scheduled posts.")
    else:
        announce(post)
        messages.success(request, "Posted.")
    return form, redirect(request.path)


def toggle_reaction(model, target, user, kind):
    """Set, change or (when it's the same one again) remove a reaction. True if a new reaction was added."""
    field = "post" if model is Reaction else "comment"
    reaction, created = model.objects.get_or_create(**{field: target}, user=user, defaults={"kind": kind})
    if created:
        return True
    if reaction.kind == kind:
        reaction.delete()
    else:
        reaction.kind = kind
        reaction.save(update_fields=["kind"])
    return False


def notify_once_a_day(recipient, actor, message, url, category):
    """Toggling something on and off must not flood the other person: one alert per day per link."""
    day_ago = timezone.now() - timedelta(days=1)
    if not Notification.objects.filter(recipient=recipient, actor=actor, url=url, created_at__gte=day_ago).exists():
        notify([recipient], actor, message, url, category=category)


# --- Feed and posts --------------------------------------------------------------

SORTS = {"new": ("Newest first", "-created_at"), "activity": ("Recent activity", "-last_activity_at")}
SCOPES = {"all": "Everything", "company": "Company-wide", "mine": "My groups and teams"}
FEED_KINDS = {"": "All posts", Post.UPDATE: "Posts", Post.NEWS: "News", Post.POLL: "Polls", Post.EVENT: "Events"}


def feed(request):
    form, done = handle_composer(request)
    if done:
        return done
    user, today = request.user, timezone.localdate()
    sort = request.GET.get("sort") if request.GET.get("sort") in SORTS else "new"
    scope = request.GET.get("scope") if request.GET.get("scope") in SCOPES else "all"
    kind = request.GET.get("type") if request.GET.get("type") in dict(Post.KINDS) else ""

    posts = post_queryset().in_feed_of(user)
    company_wide = Q(community__isnull=True, audiences__isnull=True)
    if scope == "company":
        posts = posts.filter(company_wide)
    elif scope == "mine":
        posts = posts.exclude(company_wide)
    if kind:
        posts = posts.filter(kind=kind)
    # Company and team pins go on top of the home feed. Interest groups' pins (anyone can start a group) stay on
    # top of their group's page, so five of them can't push "Office closed on Monday" out of sight.
    pins = posts.filter(pinned_at__isnull=False).exclude(community__kind=Community.GROUP)
    pinned = decorate(pins.order_by("-pinned_at")[:5], user)
    page = paginate(request, posts.exclude(pk__in=[p.pk for p in pinned]).order_by(SORTS[sort][1], "-pk"))
    now = timezone.now()
    context = {
        "nav": "feed",
        "form": form,
        "pinned": pinned if page.number == 1 else [],
        "page": page,
        "posts": decorate(page.object_list, user),
        "sort": sort, "sorts": SORTS, "scope": scope, "scopes": SCOPES, "kind": kind, "kinds": FEED_KINDS,
        "upcoming": visible_events(user).filter(Q(starts_at__gte=now) | Q(ends_at__gte=now))[:4],
        "my_groups": user.communities.all()[:8],
        "birthdays_today": birthdays_on(today),
    }
    return render(request, "hub/feed.html", context)


def post_detail(request, pk):
    post = get_post(request, pk)
    user = request.user
    if post.kind == Post.NEWS and post.is_live:
        PostRead.objects.get_or_create(post=post, user=user)
    post = decorate([post], user)[0]
    stats = None
    if post.kind == Post.NEWS and (post.author_id == user.pk or user.has_perm("hub.publish_news")):
        stats = {
            "audience": post_audience(post).exclude(pk=post.author_id).count(),
            "read": post.reads.exclude(user=post.author_id).count(),
            "acknowledged": post.reads.exclude(user=post.author_id).filter(acknowledged_at__isnull=False).count(),
        }
    context = {"post": post, "full": True, "stats": stats, "nav": "news" if post.kind == Post.NEWS else "feed"}
    return render(request, "hub/post_detail.html", context)


def _live_post(request, pk):
    return get_object_or_404(Post.objects.visible().viewable_by(request.user), pk=pk)


@require_POST
def react(request, pk):
    post = _live_post(request, pk)
    kind = request.POST.get("kind")
    if kind not in ReactionKind.values:
        return HttpResponseBadRequest("Unknown reaction")
    if toggle_reaction(Reaction, post, request.user, kind):
        post.touch()
        message = f"{request.user} reacted {Reaction.EMOJI[kind]} to your post"
        notify_once_a_day(post.author, request.user, message, post.get_absolute_url(), "reactions")
    return post_changed(request, post.pk)


@require_POST
def comment_react(request, pk):
    comment = get_object_or_404(Comment.objects.visible(), pk=pk)
    _live_post(request, comment.post_id)
    kind = request.POST.get("kind")
    if kind not in ReactionKind.values:
        return HttpResponseBadRequest("Unknown reaction")
    if toggle_reaction(CommentReaction, comment, request.user, kind):
        message = f"{request.user} reacted {Reaction.EMOJI[kind]} to your comment"
        notify_once_a_day(comment.author, request.user, message, comment.get_absolute_url(), "reactions")
    return post_changed(request, comment.post_id)


def post_reactions(request, pk):
    """Who reacted to a post, with a tab per reaction."""
    post = _live_post(request, pk)
    reactions = list(post.reactions.select_related("user"))
    counts = Counter(r.kind for r in reactions)
    kind = request.GET.get("kind") if request.GET.get("kind") in counts else ""
    context = {
        "post": post,
        "kind": kind,
        "tabs": [(k, Reaction.EMOJI[k], counts[k]) for k in ReactionKind.values if counts[k]],
        "total": len(reactions),
        "reactions": [(r.user, Reaction.EMOJI[r.kind]) for r in reactions if not kind or r.kind == kind],
    }
    return render(request, "hub/post_reactions.html", context)


@require_POST
def comment_create(request, pk):
    post = _live_post(request, pk)
    user = request.user
    if over_limit("comment", Comment.objects.filter(author=user), request):
        return HttpResponse(LIMIT_MESSAGE, status=429)
    parent = Comment.objects.visible().filter(pk=as_id(request.POST.get("parent")), post=post).first()
    if parent and parent.parent_id:
        parent = parent.parent  # replies stay one level deep
    form = CommentForm(request.POST, request.FILES)
    if not form.is_valid():
        return refuse(request, " ".join(error for errors in form.errors.values() for error in errors))
    comment = form.save(commit=False)
    comment.post, comment.author, comment.parent = post, user, parent
    comment.save()
    post.touch()
    mentioned = set_mentions(comment)

    url = comment.get_absolute_url()
    # One unread comment alert per post per person: a busy post must not send hundreds of alerts to each commenter.
    # Only comment alerts count: an unread "News: ..." or reaction alert for the post must not swallow a reply.
    already_alerted = Notification.objects.filter(
        category="comments", url__startswith=post.get_absolute_url(), read_at__isnull=True
    )
    to_tell = User.objects.filter(is_active=True).exclude(pk__in=already_alerted.values("recipient"))
    told = {post.author_id}
    notify(to_tell.filter(pk=post.author_id), user, f"{user} commented on your post", url, category="comments")
    if parent and parent.author_id not in told:
        notify(to_tell.filter(pk=parent.author_id), user, f"{user} replied to your comment", url, category="comments")
        told.add(parent.author_id)
    mention_ids = {person.pk for person in mentioned} - told
    # Every mention gets its own alert: someone asked for this person by name.
    mentioned_people = User.objects.filter(is_active=True, pk__in=mention_ids)
    notify(mentioned_people, user, f"{user} mentioned you in a comment", url, category="mentions")
    told |= mention_ids
    others = to_tell.filter(Q(comments__post=post) | Q(post_follows__post=post)).exclude(pk__in=told).distinct()
    notify(others, user, f"{user} also commented on a post", url, category="comments")
    return post_changed(request, post.pk)


def post_edit(request, pk):
    post = get_object_or_404(Post.objects.filter(is_hidden=False, deleted_at__isnull=True), pk=pk, author=request.user)
    if post.kind == Post.NEWS:
        return redirect("news_edit", post.pk)
    if post.kind == Post.EVENT:
        return redirect("event_edit", post.event_id)
    form = PostEditForm(request.POST or None, instance=post)
    if request.method == "POST" and form.is_valid():
        before = list(post.mentions.all())
        post = form.save(commit=False)
        post.edited_at = timezone.now()
        post.save(update_fields=["body", "edited_at"])
        newly = set_mentions(post, old=before)
        if post.is_live:
            notify(newly, request.user, f"{request.user} mentioned you", post.get_absolute_url(), category="mentions")
        messages.success(request, "Post updated.")
        return redirect(post)
    return render(request, "hub/post_edit.html", {"form": form, "post": post})


@require_POST
def post_pin(request, pk):
    post = _live_post(request, pk)
    if not post.can_pin(request.user):
        raise PermissionDenied
    post.pinned_at = None if post.pinned_at else timezone.now()
    post.save(update_fields=["pinned_at"])
    record_change(request.user, post, "Pinned" if post.pinned_at else "Unpinned")
    audit("post_pinned" if post.pinned_at else "post_unpinned", request, post_id=post.pk)
    return post_changed(request, post.pk)


@require_POST
def post_follow(request, pk):
    post = _live_post(request, pk)
    follow, created = PostFollow.objects.get_or_create(post=post, user=request.user)
    if not created:
        follow.delete()
    return post_changed(request, post.pk)


@require_POST
def poll_vote(request, pk):
    post = get_object_or_404(Post.objects.visible().viewable_by(request.user), pk=pk, kind=Post.POLL)
    if not post.poll_open:
        return refuse(request, "This poll has closed.")
    option = PollOption.objects.filter(pk=as_id(request.POST.get("option")), post=post).first()
    if option is None:
        return HttpResponseBadRequest("Unknown answer")
    PollVote.objects.update_or_create(post=post, user=request.user, defaults={"option": option})
    post.touch()
    return post_changed(request, post.pk)


@require_POST
def post_publish_now(request, pk):
    post = get_object_or_404(Post.objects.filter(is_hidden=False, deleted_at__isnull=True), pk=pk, author=request.user)
    if post.is_draft or post.is_scheduled:
        post.is_draft = False
        post.created_at = post.last_activity_at = timezone.now()
        post.save(update_fields=["is_draft", "created_at", "last_activity_at"])
        announce(post)
        messages.success(request, "Published.")
    return redirect(post)


def scheduled(request):
    """My scheduled posts and drafts."""
    kind = request.GET.get("type") if request.GET.get("type") in (Post.NEWS, Post.UPDATE, Post.POLL) else ""
    mine = Post.objects.filter(author=request.user, is_hidden=False, deleted_at__isnull=True)
    waiting = mine.filter(Q(is_draft=True) | Q(created_at__gt=timezone.now())).order_by("is_draft", "created_at")
    if kind:
        waiting = waiting.filter(kind=kind)
    return render(request, "hub/scheduled.html", {"nav": "menu", "posts": waiting, "kind": kind})


@require_POST
def post_delete(request, pk):
    post = get_object_or_404(Post.objects.filter(deleted_at__isnull=True), pk=pk)
    by_moderator = post.author_id != request.user.pk
    if by_moderator and not request.user.has_perm("hub.delete_post"):
        raise PermissionDenied
    soft_delete(request, post, by_moderator)
    if request.headers.get("X-Fragment"):
        return HttpResponse("")
    messages.success(request, "Post deleted.")
    return redirect("feed")


@require_POST
def comment_delete(request, pk):
    comment = get_object_or_404(Comment.objects.filter(deleted_at__isnull=True), pk=pk)
    by_moderator = comment.author_id != request.user.pk
    if by_moderator and not request.user.has_perm("hub.delete_comment"):
        raise PermissionDenied
    soft_delete(request, comment, by_moderator)
    return post_changed(request, comment.post_id)


def soft_delete(request, item, by_moderator):
    """Hide now, remove for good after DELETED_KEEP_DAYS (see the purge command), and log who did it."""
    item.soft_delete(request.user)
    who = "a moderator" if by_moderator else "its author"
    record_change(request.user, item, f"Deleted by {who}; kept {DELETED_KEEP_DAYS} days in case it's needed")
    kind = type(item).__name__.lower()
    audit(f"{kind}_deleted", request, item_id=item.pk, author_id=item.author_id, by_moderator=by_moderator)


def moderators():
    return User.objects.filter(is_active=True).filter(
        Q(is_superuser=True) | Q(user_permissions__codename="change_report") | Q(groups__permissions__codename="change_report")
    ).distinct()


def report(request, kind, pk):
    """Flag a post, a comment or a person for the moderators."""
    if kind == "post":
        target = _live_post(request, pk)
    elif kind == "comment":
        target = get_object_or_404(Comment.objects.visible(), pk=pk)
        _live_post(request, target.post_id)
    elif kind == "person":
        target = get_object_or_404(User.objects.exclude(pk=request.user.pk), pk=pk)
    else:
        raise Http404
    form = ReportForm(request.POST or None)
    if request.method == "POST" and over_limit("report", Report.objects.filter(reporter=request.user), request):
        messages.error(request, LIMIT_MESSAGE)
        return redirect(target.get_absolute_url())
    if request.method == "POST" and form.is_valid():
        form.instance.reporter = request.user
        setattr(form.instance, kind, target)
        saved = form.save()
        notify(moderators(), request.user, f"{request.user} reported a {kind}", reverse("admin:hub_report_change", args=[saved.pk]))
        audit("report_made", request, report_id=saved.pk, target=saved.target_label)
        messages.success(request, "Thanks for letting us know. A moderator will take a look.")
        return redirect(target.get_absolute_url())
    return render(request, "hub/report.html", {"form": form, "target": target, "kind": kind})


@require_POST
def translate(request, kind, pk):
    """Translate a post or comment into the reader's language, if a translation server is configured."""
    if not settings.TRANSLATE_URL:
        raise Http404
    if kind == "post":
        item = _live_post(request, pk)
        text = f"{item.title}\n\n{item.body}".strip()
    elif kind == "comment":
        item = get_object_or_404(Comment.objects.visible(), pk=pk)
        _live_post(request, item.post_id)
        text = item.body
    else:
        raise Http404
    try:
        answer = requests.post(
            settings.TRANSLATE_URL.rstrip("/") + "/translate",
            json={"q": richtext.plain(text), "source": "auto", "target": request.user.language, "format": "text",
                  "api_key": settings.TRANSLATE_API_KEY},
            timeout=15,
        )
        answer.raise_for_status()
        translated = answer.json()["translatedText"]
    except (requests.RequestException, KeyError, ValueError):
        return JsonResponse({"error": "The translation service didn't answer. Please try again later."}, status=502)
    return JsonResponse({"html": richtext.render(translated)})


# --- People ----------------------------------------------------------------------


def people(request):
    q = request.GET.get("q", "").strip()
    users = User.objects.filter(is_active=True).order_by("first_name", "last_name")
    users = matching(users, q, "first_name", "last_name", "job_title", "department", "email")
    units = Community.objects.filter(kind=Community.UNIT)
    unit = units.filter(pk=as_id(request.GET.get("unit"))).first()
    if unit:
        users = users.filter(communities=unit)
    departments = sorted(set(User.objects.filter(is_active=True).exclude(department="").values_list("department", flat=True)))
    department = request.GET.get("department", "")
    if department in departments:
        users = users.filter(department=department)
    context = {
        "nav": "menu", "page": paginate(request, users, 30), "q": q,
        "units": units, "unit": unit, "departments": departments, "department": department,
    }
    return render(request, "hub/people.html", context)


def people_suggest(request):
    """Names for the @mention helper in the composer."""
    q = request.GET.get("q", "").strip()
    if len(q) < 2:
        return JsonResponse({"people": []})
    found = User.objects.filter(is_active=True).filter(Q(first_name__istartswith=q) | Q(last_name__istartswith=q))[:8]
    return JsonResponse({"people": [{"name": str(p), "detail": p.job_title} for p in found]})


def profile(request, pk):
    person = get_object_or_404(User, pk=pk)
    page = paginate(request, post_queryset().viewable_by(request.user).filter(author=person).exclude(kind=Post.EVENT))
    context = {
        "nav": "menu", "person": person, "page": page, "posts": decorate(page.object_list, request.user),
        "units": person.communities.filter(kind=Community.UNIT),
    }
    return render(request, "hub/profile.html", context)


def profile_edit(request):
    user = request.user
    old = {"avatar": user.avatar.name, "cover": user.cover.name}
    form = ProfileForm(request.POST or None, request.FILES or None, instance=user)
    if request.method == "POST" and form.is_valid():
        form.save()
        for field, old_name in old.items():  # don't leave replaced pictures on disk
            if old_name and old_name != getattr(user, field).name:
                default_storage.delete(old_name)
        messages.success(request, "Profile saved.")
        return redirect(user)
    return render(request, "hub/profile_edit.html", {"nav": "menu", "form": form})


def birthdays_on(day):
    """Who has a birthday on this day, by the same rule as the Birthdays page (29 February counts on the 28th)."""
    born_this_month = User.objects.filter(is_active=True, birthday__month=day.month)
    return [person for person in born_this_month if next_occurrence(person.birthday, day) == day]


def birthdays(request):
    """Upcoming birthdays and work anniversaries. Only people who added the date themselves are listed."""
    today = timezone.localdate()
    staff = User.objects.filter(is_active=True)
    born = sorted(((next_occurrence(p.birthday, today), p) for p in staff.exclude(birthday=None)), key=lambda pair: pair[0])
    month_ahead = today + timedelta(days=30)
    started = []
    for person in staff.exclude(start_date=None):
        when = next_occurrence(person.start_date, today)
        years = when.year - person.start_date.year
        if years > 0 and when <= month_ahead:  # 0 or less for someone who hasn't started yet
            started.append((when, person, years))
    context = {"nav": "menu", "birthdays": born, "anniversaries": sorted(started, key=lambda row: row[0]), "today": today}
    return render(request, "hub/birthdays.html", context)


# --- Groups and the organisation ---------------------------------------------------


def _community_list(request, kind):
    q = request.GET.get("q", "").strip()
    show = "all" if request.GET.get("show") == "all" else "mine"
    found = Community.objects.filter(kind=kind).select_related("parent").annotate(member_count=Count("members"))
    if q:
        found = matching(found, q, "name", "description")
    mine = set(request.user.communities.values_list("pk", flat=True))
    if show == "mine" and not q:
        found = found.filter(pk__in=mine)
    return {"nav": "menu", "mine": mine, "show": show, "q": q}, found


def communities(request):
    context, groups = _community_list(request, Community.GROUP)
    return render(request, "hub/communities.html", context | {"groups": groups})


def organisation(request):
    context, units = _community_list(request, Community.UNIT)
    return render(request, "hub/organisation.html", context | {"units": units.order_by("unit_type", "name")})


def unique_slug(name):
    base = slugify(name)[:120] or "group"
    slug, n = base, 2
    while slug == "new" or Community.objects.filter(slug=slug).exists():
        slug, n = f"{base}-{n}", n + 1
    return slug


def community_create(request):
    form = CommunityForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and over_limit("group", Community.objects.filter(created_by=request.user), request):
        messages.error(request, LIMIT_MESSAGE)
    elif request.method == "POST" and form.is_valid():
        group = form.save(commit=False)
        group.slug = unique_slug(group.name)
        group.created_by = request.user
        group.save()
        group.members.add(request.user)
        group.admins.add(request.user)
        messages.success(request, f"{group} is ready. Invite colleagues from the Members tab.")
        return redirect(group)
    return render(request, "hub/community_form.html", {"nav": "menu", "form": form})


def community_edit(request, slug):
    group = get_object_or_404(Community, slug=slug)
    if not group.is_admin(request.user):
        raise PermissionDenied
    old_cover = group.cover.name
    form = CommunityForm(request.POST or None, request.FILES or None, instance=group)
    if group.is_unit:
        del form.fields["is_private"]  # units are always for their members only
    if request.method == "POST" and form.is_valid():
        form.save()
        if old_cover and old_cover != group.cover.name:
            default_storage.delete(old_cover)
        messages.success(request, "Saved.")
        return redirect(group)
    return render(request, "hub/community_form.html", {"nav": "menu", "form": form, "group": group})


def _open_invite(group, user):
    return GroupInvite.objects.filter(community=group, user=user, answered_at__isnull=True).first()


def community_detail(request, slug):
    group = get_object_or_404(Community, slug=slug)
    user = request.user
    is_member = group.has_member(user)
    base = {
        "nav": "menu", "group": group, "is_member": is_member, "is_admin": group.is_admin(user),
        "member_count": group.members.count(), "can_view": group.can_view(user), "open_invite": _open_invite(group, user),
    }
    if not base["can_view"]:
        if request.method == "POST":
            raise PermissionDenied
        return render(request, "hub/community.html", base)
    form = None
    if is_member:
        form, done = handle_composer(request, community=group)
        if done:
            return done
    elif request.method == "POST":
        raise PermissionDenied
    posts = post_queryset().filter(community=group)
    pinned = decorate(posts.filter(pinned_at__isnull=False).order_by("-pinned_at")[:5], user)
    page = paginate(request, posts.exclude(pk__in=[p.pk for p in pinned]))
    now = timezone.now()
    context = base | {
        "form": form,
        "pinned": pinned if page.number == 1 else [],
        "page": page,
        "posts": decorate(page.object_list, user),
        "events": group.events.filter(Q(starts_at__gte=now) | Q(ends_at__gte=now))[:5],
        "members": group.members.all()[:12],
    }
    return render(request, "hub/community.html", context)


def community_members(request, slug):
    group = get_object_or_404(Community, slug=slug)
    if not group.can_view(request.user):
        raise Http404
    is_admin = group.is_admin(request.user)
    q = request.GET.get("q", "").strip()
    context = {
        "nav": "menu", "group": group, "is_admin": is_admin, "q": q,
        "is_member": group.has_member(request.user),
        "admin_ids": set(group.admins.values_list("pk", flat=True)),
        "page": paginate(request, group.members.order_by("first_name", "last_name"), 40),
    }
    if is_admin:
        context["requests"] = group.invites.filter(kind=GroupInvite.REQUEST, answered_at__isnull=True).select_related("user")
        context["invited"] = group.invites.filter(kind=GroupInvite.INVITE, answered_at__isnull=True).select_related("user")
        if len(q) >= 2:
            outsiders = matching(User.objects.filter(is_active=True).exclude(communities=group), q, "first_name", "last_name")
            context["found"] = outsiders[:20]
    return render(request, "hub/community_members.html", context)


@require_POST
def community_join(request, slug):
    group = get_object_or_404(Community, slug=slug)
    user = request.user
    if group.is_unit:
        raise PermissionDenied  # units follow the organisation; an admin places people
    if group.can_join(user):
        group.members.add(user)
        messages.success(request, f"You joined {group}.")
    elif not group.has_member(user) and not _open_invite(group, user):
        # A private group: ask its admins.
        invite = GroupInvite.objects.create(community=group, user=user, kind=GroupInvite.REQUEST, created_by=user)
        url = reverse("community_members", args=[group.slug])
        notify(group.admins.filter(is_active=True), user, f"{user} asked to join {group}", url, category="groups", invite=invite)
        messages.success(request, "Your request was sent to the group's admins.")
    return redirect(group)


@require_POST
def community_leave(request, slug):
    group = get_object_or_404(Community, slug=slug)
    if group.is_unit:
        raise PermissionDenied
    user = request.user
    group.members.remove(user)
    group.admins.remove(user)
    if not group.admins.filter(is_active=True).exists():
        # Someone must still answer join requests and invite people: the longest-standing member takes over.
        heir = group.members.through.objects.filter(community=group, user__is_active=True).order_by("pk").first()
        if heir:
            group.admins.add(heir.user_id)
            notify([heir.user], user, f"You are now an admin of {group}", group.get_absolute_url(), category="groups")
    messages.success(request, f"You left {group}.")
    return redirect("communities")


@require_POST
def community_invite(request, slug):
    group = get_object_or_404(Community, slug=slug)
    user = request.user
    if not group.is_admin(user):
        raise PermissionDenied
    person = get_object_or_404(User, pk=as_id(request.POST.get("user")), is_active=True)
    if group.is_unit:
        group.members.add(person)  # units have no invitations: an admin places people
        notify([person], user, f"You were added to {group}", group.get_absolute_url(), category="groups")
    elif not group.has_member(person) and not _open_invite(group, person):
        invite = GroupInvite.objects.create(community=group, user=person, kind=GroupInvite.INVITE, created_by=user)
        notify([person], user, f"{user} invited you to the group {group}", group.get_absolute_url(), category="groups", invite=invite)
    audit("group_member_added" if group.is_unit else "group_invite_sent", request, group=group.slug, person_id=person.pk)
    return redirect("community_members", group.slug)


@require_POST
def invite_answer(request, pk):
    """Accept or decline: the invited person answers an invitation; a group admin answers a request to join."""
    invite = get_object_or_404(GroupInvite.objects.select_related("community", "user"), pk=pk, answered_at__isnull=True)
    group, user = invite.community, request.user
    allowed = invite.user_id == user.pk if invite.kind == GroupInvite.INVITE else group.is_admin(user)
    if not allowed:
        raise PermissionDenied
    invite.accepted = request.POST.get("answer") == "accept"
    invite.answered_at = timezone.now()
    invite.save(update_fields=["accepted", "answered_at"])
    invite.notifications.filter(read_at__isnull=True).update(read_at=timezone.now())
    if invite.accepted:
        group.members.add(invite.user)
    if invite.kind == GroupInvite.REQUEST:
        verdict = "approved" if invite.accepted else "declined"
        notify([invite.user], user, f"Your request to join {group} was {verdict}", group.get_absolute_url(), category="groups")
        return redirect("community_members", group.slug)
    messages.success(request, f"You joined {group}." if invite.accepted else "Invitation declined.")
    return redirect(group) if invite.accepted else redirect("notifications")


@require_POST
def community_member_change(request, slug, user_id):
    """Group admins: remove a member, or make someone an admin (or take that away)."""
    group = get_object_or_404(Community, slug=slug)
    if not group.is_admin(request.user):
        raise PermissionDenied
    person = get_object_or_404(group.members, pk=user_id)
    action = request.POST.get("action")
    if action == "remove":
        group.members.remove(person)
        group.admins.remove(person)
        notify([person], request.user, f"You were removed from {group}", reverse("communities"), category="groups")
    elif action == "admin":
        group.admins.add(person)
    elif action == "unadmin" and group.admins.count() > 1:
        group.admins.remove(person)
    audit("group_member_changed", request, group=group.slug, person_id=person.pk, action=action)
    return redirect("community_members", group.slug)


# --- Events ----------------------------------------------------------------------


def can_manage_event(user, event):
    return event.created_by_id == user.pk or user.has_perm("hub.change_event")


def events(request):
    now = timezone.now()
    past = request.GET.get("past") == "1"
    q = request.GET.get("q", "").strip()
    reply = request.GET.get("reply") if request.GET.get("reply") in (*RSVP.Status.values, "none") else ""
    upcoming = Q(starts_at__gte=now) | Q(ends_at__gte=now)
    qs = visible_events(request.user)
    qs = qs.exclude(upcoming).order_by("-starts_at") if past else qs.filter(upcoming)
    if q:
        qs = matching(qs, q, "title", "location")
    mine = RSVP.objects.filter(user=request.user)
    if reply == "none":
        qs = qs.exclude(pk__in=mine.values("event"))
    elif reply:
        qs = qs.filter(pk__in=mine.filter(status=reply).values("event"))
    page = paginate(request, qs)
    statuses = dict(mine.filter(event__in=list(page.object_list)).values_list("event_id", "status"))
    for event in page.object_list:
        event.my_status = RSVP.Status(statuses[event.pk]).label if event.pk in statuses else None
    context = {"nav": "menu", "page": page, "past": past, "q": q, "reply": reply, "replies": RSVP.Status.choices}
    return render(request, "hub/events.html", context)


def event_create(request):
    form = EventForm(request.POST or None, user=request.user)
    if request.method == "POST" and over_limit("event", Event.objects.filter(created_by=request.user), request):
        messages.error(request, LIMIT_MESSAGE)
    elif request.method == "POST" and form.is_valid():
        form.instance.created_by = request.user
        event = form.save()
        RSVP.objects.create(event=event, user=request.user, status=RSVP.Status.GOING)
        # The event also shows as a card in the feed of the people it is for.
        Post.objects.create(kind=Post.EVENT, author=request.user, community=event.community, event=event, notified_at=timezone.now())
        if event.community:
            message = f"{request.user} created an event in {event.community}: {event.title}"
            notify(event.community.members.filter(is_active=True), request.user, message, event.get_absolute_url(), category="events")
        messages.success(request, "Event created.")
        return redirect(event)
    return render(request, "hub/event_form.html", {"nav": "menu", "form": form})


def event_edit(request, pk):
    event = get_object_or_404(Event, pk=pk)
    if not can_manage_event(request.user, event):
        raise PermissionDenied
    form = EventForm(request.POST or None, instance=event, user=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        if "starts_at" in form.changed_data:  # reminders already sent were for the old time
            ReminderSent.objects.filter(rsvp__event=event).delete()
        Post.objects.filter(event=event).update(community=event.community)
        attending = [r.user for r in event.rsvps.select_related("user").exclude(status=RSVP.Status.DECLINED)]
        notify(attending, request.user, f"{request.user} updated the event: {event.title}", event.get_absolute_url(), category="events")
        messages.success(request, "Event updated. People who said they're going have been told.")
        return redirect(event)
    return render(request, "hub/event_form.html", {"nav": "menu", "form": form, "event": event})


@require_POST
def event_delete(request, pk):
    event = get_object_or_404(Event, pk=pk)
    by_moderator = event.created_by_id != request.user.pk
    if by_moderator and not request.user.has_perm("hub.delete_event"):
        raise PermissionDenied
    record_change(request.user, event, f"Deleted by {'a moderator' if by_moderator else 'its organiser'}", deletion=True)
    audit("event_deleted", request, event_id=event.pk, title=event.title, by_moderator=by_moderator)
    event.delete()
    messages.success(request, "Event deleted.")
    return redirect("events")


def _event_for(request, pk):
    event = get_object_or_404(Event.objects.select_related("community", "created_by"), pk=pk)
    if not event.can_view(request.user):
        raise Http404
    return event


def event_detail(request, pk):
    event = _event_for(request, pk)
    rsvps = list(event.rsvps.select_related("user"))
    mine = next((r for r in rsvps if r.user_id == request.user.pk), None)
    context = {
        "nav": "menu",
        "event": event,
        "going": [r.user for r in rsvps if r.status == RSVP.Status.GOING],
        "maybe": [r.user for r in rsvps if r.status == RSVP.Status.MAYBE],
        "mine": mine.status if mine else None,
        "statuses": RSVP.Status.choices,
        "can_manage": can_manage_event(request.user, event),
        "reminder_form": ReminderForm(initial={"reminders": mine.reminder_minutes()}) if mine else None,
    }
    return render(request, "hub/event.html", context)


@require_POST
def rsvp(request, pk):
    event = _event_for(request, pk)
    status = request.POST.get("status")
    if status not in RSVP.Status.values:
        return HttpResponseBadRequest("Unknown RSVP")
    RSVP.objects.update_or_create(event=event, user=request.user, defaults={"status": status})
    return redirect(event)


@require_POST
def event_reminders(request, pk):
    """Reminder times for this one event, overriding the person's default."""
    event = _event_for(request, pk)
    mine = get_object_or_404(RSVP, event=event, user=request.user)
    form = ReminderForm(request.POST)
    if form.is_valid():
        mine.reminders = form.cleaned_data["reminders"]
        mine.save(update_fields=["reminders"])
        messages.success(request, "Reminders saved for this event.")
    return redirect(event)


def _ics_text(value):
    return value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r\n", "\\n").replace("\n", "\\n")


def event_ics(request, pk):
    """A calendar file, so staff can add the event to Outlook, Google or Apple Calendar."""
    event = _event_for(request, pk)

    def utc(dt):
        return dt.astimezone(dt_timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    ends = event.ends_at or event.starts_at + timedelta(hours=1)
    # shortcut: long lines are not folded at 75 characters as RFC 5545 asks; Outlook, Google and Apple accept them.
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:-//{_ics_text(settings.SITE_NAME)}//EN",
        "BEGIN:VEVENT",
        f"UID:event-{event.pk}@{request.get_host()}",
        f"DTSTAMP:{utc(timezone.now())}",
        f"DTSTART:{utc(event.starts_at)}",
        f"DTEND:{utc(ends)}",
        f"SUMMARY:{_ics_text(event.title)}",
        f"LOCATION:{_ics_text(event.location)}",
        f"DESCRIPTION:{_ics_text(event.description)}",
        f"URL:{request.build_absolute_uri(event.get_absolute_url())}",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    response = HttpResponse("\r\n".join(lines) + "\r\n", content_type="text/calendar; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="event-{event.pk}.ics"'
    return response
