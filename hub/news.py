"""News: longer items with a title and cover, sent to everyone or to chosen groups and units.

Readers are tracked so people can filter "Unread", and so important items can ask for a confirmation.
"""

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.files.storage import default_storage
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import NewsForm
from .models import Community, Post, PostRead, matching
from .publishing import announce, post_audience, set_mentions
from .security import LIMIT_MESSAGE, audit, over_limit
from .views import paginate

FILTERS = [("all", "All news"), ("unread", "Unread"), ("drafts", "Drafts"), ("mine", "Published by me"), ("scheduled", "Scheduled")]


def can_publish(user):
    return user.has_perm("hub.publish_news")


def news(request):
    user = request.user
    publisher = can_publish(user)
    show = request.GET.get("show") if request.GET.get("show") in dict(FILTERS) else "all"
    if show in ("drafts", "mine", "scheduled") and not publisher:
        show = "all"
    q = request.GET.get("q", "").strip()
    own = Post.objects.filter(kind=Post.NEWS, author=user, is_hidden=False, deleted_at__isnull=True)
    if show == "drafts":
        items = own.filter(is_draft=True)
    elif show == "scheduled":
        items = own.filter(is_draft=False, created_at__gt=timezone.now())
    elif show == "mine":
        items = Post.objects.visible().filter(kind=Post.NEWS, author=user)
    else:
        items = Post.objects.visible().in_feed_of(user).filter(kind=Post.NEWS)
        if show == "unread":
            items = items.exclude(reads__user=user).exclude(author=user)
    if q:
        items = matching(items, q, "title", "body")
    visible_comment = Q(comments__is_hidden=False, comments__deleted_at__isnull=True)
    items = (
        items.select_related("author").prefetch_related("audiences")
        .annotate(reaction_count=Count("reactions", distinct=True), comment_count=Count("comments", filter=visible_comment, distinct=True))
        .order_by("-created_at")
    )
    page = paginate(request, items)
    read = set(PostRead.objects.filter(post__in=list(page.object_list), user=user).values_list("post_id", flat=True))
    for item in page.object_list:
        item.is_read = item.pk in read or item.author_id == user.pk
    filters = [f for f in FILTERS if publisher or f[0] in ("all", "unread")]
    context = {"nav": "news", "page": page, "show": show, "q": q, "filters": filters, "can_publish": publisher}
    return render(request, "hub/news.html", context)


def news_compose(request, pk=None):
    """Write, edit, schedule or publish a news item."""
    user = request.user
    if not can_publish(user):
        raise PermissionDenied
    post = get_object_or_404(Post, pk=pk, kind=Post.NEWS, deleted_at__isnull=True) if pk else None
    if post and post.author_id != user.pk and not user.has_perm("hub.change_post"):
        raise PermissionDenied
    old_cover = post.cover.name if post else ""
    form = NewsForm(request.POST or None, request.FILES or None, instance=post)
    if request.method == "POST" and not post and over_limit("post", Post.objects.filter(author=user), request):
        messages.error(request, LIMIT_MESSAGE)
    elif request.method == "POST" and form.is_valid():
        as_draft = "draft" in request.POST
        post = form.save(author=user, as_draft=as_draft)
        if old_cover and old_cover != post.cover.name:
            default_storage.delete(old_cover)
        set_mentions(post)
        audit("news_saved", request, post_id=post.pk, draft=as_draft, scheduled=post.is_scheduled)
        if as_draft:
            messages.success(request, "Draft saved. Only you can see it.")
            return redirect(reverse("news") + "?show=drafts")
        if post.is_scheduled:
            when = timezone.localtime(post.created_at).strftime("%d %b at %H:%M")
            messages.success(request, f"Scheduled for {when}.")
            return redirect(reverse("news") + "?show=scheduled")
        announce(post)
        messages.success(request, "Published.")
        return redirect(post)
    return render(request, "hub/news_form.html", {"nav": "news", "form": form, "post": post})


@require_POST
def news_ack(request, pk):
    """"I've read this": the reader's confirmation on news that asks for one."""
    post = get_object_or_404(Post.objects.visible().viewable_by(request.user), pk=pk, kind=Post.NEWS, requires_ack=True)
    PostRead.objects.update_or_create(post=post, user=request.user, defaults={"acknowledged_at": timezone.now()})
    audit("news_acknowledged", request, post_id=post.pk)
    messages.success(request, "Thanks. Your confirmation is recorded.")
    return redirect(post)


def news_readers(request, pk):
    """For the publisher of a must-read item: who has confirmed and who hasn't yet."""
    # viewable_by: a publisher outside a private group must not learn who is in it from its news.
    post = get_object_or_404(Post.objects.visible().viewable_by(request.user), pk=pk, kind=Post.NEWS)
    if post.author_id != request.user.pk and not can_publish(request.user):
        raise PermissionDenied
    if any(not g.can_view(request.user) for g in post.audiences.filter(kind=Community.GROUP)):
        raise Http404  # units are left out: Communications send news to any unit and still follow it up
    if not post.requires_ack:
        raise Http404  # ordinary news only shows totals: nobody is watched for simply reading
    confirmed = {read.user_id: read.acknowledged_at for read in post.reads.exclude(acknowledged_at=None)}
    audience = list(post_audience(post).exclude(pk=post.author_id).order_by("first_name", "last_name"))
    done = [(person, confirmed[person.pk]) for person in audience if person.pk in confirmed]
    context = {"nav": "news", "post": post, "done": done, "waiting": [p for p in audience if p.pk not in confirmed]}
    return render(request, "hub/news_readers.html", context)
