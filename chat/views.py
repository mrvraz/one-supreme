from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, OuterRef, Prefetch, Q, Subquery
from django.db.models.functions import Coalesce
from django.http import Http404, HttpResponse, JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from hub.media import process_upload
from hub.models import Notification, Report, User, matching, notify
from hub.security import LIMIT_MESSAGE, audit, over_limit
from hub.views import moderators

from .models import Conversation, Membership, Message, unread

PAGE = 200  # messages shown at once, and the most one poll returns
MAX_BODY = Message._meta.get_field("body").max_length
MAX_NAME = Conversation._meta.get_field("name").max_length


def member_or_404(request, pk):
    """This person's membership of the chat. Non-members get "not found", so they can't tell which chats exist."""
    return get_object_or_404(Membership.objects.select_related("conversation"), conversation_id=pk, user=request.user)


def colleagues(user, q=""):
    """Active colleagues whose name contains every word of q."""
    people = User.objects.filter(is_active=True).exclude(pk=user.pk).order_by("first_name", "last_name")
    return matching(people, q, "first_name", "last_name")


def ids(values):
    return [int(v) for v in values if v.isdecimal()]


def mark_read(membership):
    now = timezone.now()
    membership.last_read_at = now
    membership.save(update_fields=["last_read_at"])
    Notification.objects.filter(
        recipient=membership.user, category="messages", url=membership.conversation.get_absolute_url(), read_at__isnull=True
    ).update(read_at=now)


# --- Lists and starting a chat ------------------------------------------------------


def chat_list(request):
    me = request.user
    unread_count = unread().order_by().values("conversation").annotate(n=Count("pk")).values("n")
    latest = Message.objects.filter(conversation=OuterRef("conversation")).order_by("-pk").values("pk")[:1]
    rows = (
        Membership.objects.filter(user=me)
        # A one-to-one chat appears once someone has written in it. Group chats appear as soon as you are added.
        .filter(Q(conversation__last_message_at__isnull=False) | Q(conversation__is_group=True))
        .select_related("conversation")
        .prefetch_related(Prefetch(  # only one-to-one chats need their members, to show the other person
            "conversation__memberships", Membership.objects.filter(conversation__is_group=False).select_related("user")
        ))
        .annotate(unread=Coalesce(Subquery(unread_count), 0), latest_id=Subquery(latest))
        .order_by(Coalesce("conversation__last_message_at", "conversation__created_at").desc())
    )
    page = Paginator(rows, 30).get_page(request.GET.get("page"))
    latest_messages = Message.objects.select_related("sender").in_bulk([row.latest_id for row in page if row.latest_id])
    for row in page:
        row.other = row.conversation.other(me)
        row.title = row.conversation.label_for(me)
        row.latest = latest_messages.get(row.latest_id)
    return render(request, "chat/list.html", {"nav": "chat", "page": page})


def new(request):
    """Pick one colleague to message, or (with ?group) name a group chat and tick its members.

    The group form posts for its search too, so the name and the people already ticked survive a new search.
    """
    me = request.user
    group = "group" in request.GET
    q = request.POST.get("q", request.GET.get("q", "")).strip()
    name = request.POST.get("name", "").strip()
    picked = list(colleagues(me).filter(pk__in=ids(request.POST.getlist("members"))))
    error = ""
    if request.method == "POST" and "create" in request.POST:
        if not name or len(name) > MAX_NAME:
            error = f"Give the group chat a name of up to {MAX_NAME} characters."
        elif len(picked) < 2:
            error = "Tick at least 2 colleagues. To message one person, use “One colleague”."
        elif over_limit("group", Conversation.objects.filter(created_by=me, is_group=True), request):
            return HttpResponse(LIMIT_MESSAGE, status=429)
        else:
            with transaction.atomic():
                conversation = Conversation.objects.create(is_group=True, name=name, created_by=me)
                Membership.objects.bulk_create(Membership(conversation=conversation, user=u) for u in [me, *picked])
            return redirect(conversation)
    found = colleagues(me, q).exclude(pk__in=[p.pk for p in picked])[:50]
    context = {
        "nav": "chat", "group": group, "q": q, "name": name, "error": error, "people": found,
        "choices": [(p, True) for p in picked] + [(p, False) for p in found],
    }
    return render(request, "chat/new.html", context)


def with_person(request, user_id):
    """Open my one-to-one chat with this colleague, creating it the first time.

    Reached by plain links ("Message" on a profile), so it also works as a GET. That is safe: an empty chat
    shows in nobody's list, and the database allows only one chat per pair.
    """
    person = get_object_or_404(colleagues(request.user), pk=user_id)  # active, and not me
    low, high = sorted([request.user.pk, person.pk])
    with transaction.atomic():
        conversation, created = Conversation.objects.get_or_create(pair=f"{low}:{high}", defaults={"created_by": request.user})
        if created:
            Membership.objects.bulk_create(Membership(conversation=conversation, user=u) for u in (request.user, person))
    return redirect(conversation)


# --- One chat -------------------------------------------------------------------------


def thread(request, pk):
    membership = member_or_404(request, pk)
    conversation = membership.conversation
    # Nothing from before you joined: someone re-added to a group must not read what was said while they were out.
    found = conversation.messages.filter(created_at__gte=membership.joined_at).select_related("sender").order_by("-pk")
    before = request.GET.get("before", "")
    if before.isdecimal():
        found = found.filter(pk__lt=before)
    msgs = list(found[: PAGE + 1])[::-1]
    earlier = len(msgs) > PAGE  # one extra was fetched to learn whether older messages exist
    msgs = msgs[-PAGE:]
    mark_read(membership)
    context = {
        "nav": "chat", "conversation": conversation, "membership": membership, "msgs": msgs,
        "other": conversation.other(request.user), "title": conversation.label_for(request.user),
        "earlier": msgs[0].pk if earlier else None, "last_id": msgs[-1].pk if msgs else 0, "max_body": MAX_BODY,
        "older_page": before.isdecimal(),  # no message box there: it would pull in the newest messages
    }
    return render(request, "chat/thread.html", context)


def poll(request, pk):
    """Messages newer than ?after=<id>, as HTML for chat.js to append.

    shortcut: a message deleted after it was shown stays on other people's screens until they reload;
    send deletions through here too if that becomes a problem.
    """
    membership = member_or_404(request, pk)
    after = request.GET.get("after", "")
    after = int(after) if after.isdecimal() else 0
    since_joining = membership.conversation.messages.filter(created_at__gte=membership.joined_at)
    msgs = list(since_joining.select_related("sender").filter(pk__gt=after)[:PAGE])
    if not msgs:  # the usual answer: skip rendering, which would also count every badge on the page
        return JsonResponse({"html": "", "last_id": after})
    mark_read(membership)  # the page only polls while it is on screen, so these have been seen
    # Without request: context processors would count every badge on the page for a fragment that shows none.
    context = {"msgs": msgs, "conversation": membership.conversation, "user": request.user, "csrf_token": get_token(request)}
    html = render_to_string("chat/_messages.html", context)
    return JsonResponse({"html": html, "last_id": msgs[-1].pk})


@require_POST
def send(request, pk):
    conversation = member_or_404(request, pk).conversation
    me = request.user
    mine = Message.objects.filter(sender=me)
    upload = request.FILES.get("image")
    if over_limit("message", mine, request) or (upload and over_limit("file", mine.exclude(image=""), request)):
        return HttpResponse(LIMIT_MESSAGE, status=429)
    body = request.POST.get("body", "").strip()
    image, error = "", ""
    if len(body) > MAX_BODY:
        error = f"A message can be up to {MAX_BODY} characters long."
    elif upload:
        try:
            image, _ = process_upload(upload, video=False)
        except ValidationError as problem:
            error = problem.messages[0]
    elif not body:
        error = "Write a message or add a picture."
    if error:
        if request.headers.get("X-Fragment"):
            return HttpResponse(error, status=400)
        messages.error(request, error)
        return redirect(conversation)

    message = Message.objects.create(conversation=conversation, sender=me, body=body, image=image)
    Conversation.objects.filter(pk=conversation.pk).update(last_message_at=message.created_at)
    url = conversation.get_absolute_url()
    # One unread alert per chat per person: a lively chat must not send an alert for every message.
    listening = User.objects.filter(is_active=True, chat_memberships__conversation=conversation, chat_memberships__muted=False)
    alerted = Notification.objects.filter(recipient__in=listening, category="messages", url=url, read_at__isnull=True)
    text = f"{me} wrote in {conversation.name}" if conversation.is_group else f"{me} sent you a message"
    notify(listening.exclude(pk__in=alerted.values("recipient")), me, text, url, category="messages")
    if request.headers.get("X-Fragment"):
        return JsonResponse({"id": message.pk})  # chat.js then fetches it through poll, like any new message
    return redirect(conversation)


@require_POST
def mute(request, pk):
    membership = member_or_404(request, pk)
    membership.muted = not membership.muted
    membership.save(update_fields=["muted"])
    return redirect(membership.conversation)


@require_POST
def leave(request, pk):
    membership = member_or_404(request, pk)
    conversation = membership.conversation
    if not conversation.is_group:
        raise Http404
    membership.delete()
    if not conversation.memberships.exists():
        conversation.delete()  # nobody is left to read it
    elif conversation.created_by_id == request.user.pk:
        # Someone must still be able to add and remove people: whoever has been in the chat longest takes over.
        Conversation.objects.filter(pk=conversation.pk).update(created_by=conversation.manager_id())
    messages.success(request, f"You left {conversation.name}.")
    return redirect("chat:list")


def members(request, pk):
    """Who is in a group chat. Its manager (created_by: who started it, or took over in leave) adds and removes people."""
    conversation = member_or_404(request, pk).conversation
    if not conversation.is_group:
        raise Http404
    manager_id = conversation.manager_id()
    is_manager = manager_id == request.user.pk
    if request.method == "POST":
        if not is_manager:
            raise PermissionDenied
        for person in colleagues(request.user).filter(pk__in=ids([request.POST.get("add", "")])):
            Membership.objects.get_or_create(conversation=conversation, user=person)
            audit("chat_member_added", request, conversation_id=conversation.pk, person_id=person.pk)
        for removed in conversation.memberships.filter(user__in=ids([request.POST.get("remove", "")])).exclude(user=request.user):
            removed.delete()
            audit("chat_member_removed", request, conversation_id=conversation.pk, person_id=removed.user_id)
        return redirect(request.get_full_path())
    q = request.GET.get("q", "").strip()
    context = {
        "nav": "chat", "conversation": conversation, "is_manager": is_manager, "manager_id": manager_id, "q": q,
        "memberships": conversation.memberships.select_related("user").order_by("user__first_name", "user__last_name"),
        "found": colleagues(request.user, q).exclude(chat_memberships__conversation=conversation)[:30] if is_manager and q else [],
    }
    return render(request, "chat/members.html", context)


# --- Single messages --------------------------------------------------------------------


@require_POST
def delete_message(request, pk):
    """Soft delete: shown as "Message deleted" and removed for good 30 days later (see hooks.purge)."""
    message = get_object_or_404(
        Message, pk=pk, sender=request.user, deleted_at__isnull=True, conversation__memberships__user=request.user
    )
    message.deleted_at = timezone.now()
    message.save(update_fields=["deleted_at"])
    audit("chat_message_deleted", request, message_id=message.pk, conversation_id=message.conversation_id)
    return redirect(message.conversation)


@require_POST
def report(request, pk):
    message = get_object_or_404(
        Message.objects.exclude(sender=request.user).select_related("sender", "conversation"),
        pk=pk, deleted_at__isnull=True, conversation__memberships__user=request.user,
    )
    words = request.POST.get("reason", "").strip()
    if over_limit("report", Report.objects.filter(reporter=request.user), request):
        messages.error(request, LIMIT_MESSAGE)
    elif not words:
        messages.error(request, "Say what is wrong with the message, so a moderator knows what to look for.")
    else:
        # The quote comes from the database, never from the form, so a report can't put words in someone's mouth.
        # Lengths are cut to fit Report.reason (3,000 characters).
        picture = f", with picture {message.image.name}" if message.image else ""
        sent = timezone.localtime(message.created_at).strftime("%d %b %Y %H:%M")
        reason = f'"{message.body[:2000]}"\n(chat message {message.pk}, sent {sent}{picture})\n\n{words[:800]}'
        saved = Report.objects.create(reporter=request.user, person=message.sender, reason=reason)
        admin_url = reverse("admin:hub_report_change", args=[saved.pk])
        notify(moderators(), request.user, f"{request.user} reported a chat message", admin_url)
        audit("chat_message_reported", request, report_id=saved.pk, message_id=message.pk, sender_id=message.sender_id)
        messages.success(request, "Thanks for letting us know. A moderator will take a look.")
    return redirect(message.conversation)
