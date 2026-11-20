from collections import Counter

from django.contrib import messages
from django.contrib.auth.decorators import permission_required
from django.db.models import Count
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format
from django.views.decorators.http import require_POST

from hub.models import matching
from hub.security import audit

from .forms import JourneyForm, StepForm
from .models import Assignment, Journey, Step, StepDone, assign, ensure_assignments

FILTERS = [("all", "All"), ("incomplete", "Incomplete"), ("completed", "Completed")]

editor_only = permission_required("journeys.change_journey", raise_exception=True)


def is_editor(user):
    return user.has_perm("journeys.change_journey")


# --- Helpers ---------------------------------------------------------------------


def add_progress(assignments):
    """Give each assignment `total` (steps in its journey), `done` (steps its person has finished) and `percent`."""
    assignments = list(assignments)
    journeys = {a.journey_id for a in assignments}
    totals = Counter(Step.objects.filter(journey__in=journeys).values_list("journey_id", flat=True))
    ticks = StepDone.objects.filter(step__journey__in=journeys, user__in={a.user_id for a in assignments})
    done = Counter(ticks.values_list("step__journey_id", "user_id"))
    for a in assignments:
        a.total, a.done = totals[a.journey_id], done[(a.journey_id, a.user_id)]
        a.percent = round(100 * a.done / a.total) if a.total else 0
    return assignments


def open_journey(request, pk):
    """The journey, this person's assignment (or None) and whether they are an editor. 404 if they may not open it."""
    journey = get_object_or_404(Journey, pk=pk)
    editor = is_editor(request.user)
    assignment = Assignment.objects.filter(journey=journey, user=request.user).first()
    if not editor and (assignment is None or not journey.is_published):
        raise Http404
    return journey, assignment, editor


def steps_for(journey, user):
    """The journey's steps in order, each with its `number`, `is_done`, and `is_open` (every earlier step is done)."""
    done = set(StepDone.objects.filter(user=user, step__journey=journey).values_list("step_id", flat=True))
    steps, earlier_done = list(journey.steps.all()), True
    for number, step in enumerate(steps, 1):
        step.number, step.is_done, step.is_open = number, step.pk in done, earlier_done
        earlier_done = earlier_done and step.is_done
    return steps


def pick_step(steps, step_pk):
    step = next((s for s in steps if s.pk == step_pk), None)
    if step is None:
        raise Http404
    return step


# --- Pages for everyone ----------------------------------------------------------


def journey_list(request):
    ensure_assignments(request.user)
    show = request.GET.get("show", "all")
    mine = Assignment.objects.filter(user=request.user, journey__is_published=True)
    if show == "incomplete":
        mine = mine.filter(completed_at__isnull=True)
    elif show == "completed":
        mine = mine.filter(completed_at__isnull=False)
    context = {
        "nav": "menu",
        "filters": FILTERS,
        "show": show,
        "assignments": add_progress(mine.select_related("journey").order_by("-assigned_at")),
        "editor": is_editor(request.user),
    }
    if context["editor"]:  # drafts first
        context["manage"] = Journey.objects.annotate(step_count=Count("steps")).order_by("is_published", "title")
    return render(request, "journeys/list.html", context)


def detail(request, pk):
    journey, assignment, editor = open_journey(request, pk)
    steps = steps_for(journey, request.user)
    done = sum(step.is_done for step in steps)
    context = {
        "nav": "menu",
        "journey": journey,
        "assignment": assignment,
        "editor": editor,
        "steps": steps,
        "done": done,
        "percent": round(100 * done / len(steps)) if steps else 0,
        "next_step": next((step for step in steps if not step.is_done), None),
    }
    return render(request, "journeys/detail.html", context)


def step_detail(request, pk, step_pk):
    journey, assignment, editor = open_journey(request, pk)
    steps = steps_for(journey, request.user)
    current = pick_step(steps, step_pk)
    if not (current.is_open or editor):
        messages.error(request, "Finish the earlier steps first.")
        return redirect(journey)
    context = {
        "nav": "menu",
        "journey": journey,
        "step": current,
        "total": len(steps),
        "next_step": steps[current.number] if current.number < len(steps) else None,
        "can_finish": assignment is not None and current.is_open,
    }
    return render(request, "journeys/step.html", context)


@require_POST
def step_done(request, pk, step_pk):
    journey, assignment, _editor = open_journey(request, pk)
    steps = steps_for(journey, request.user)
    current = pick_step(steps, step_pk)
    # Steps are done in order, by editors too. Only people the journey was given to keep progress.
    if assignment is None or not current.is_open:
        messages.error(
            request, "Finish the earlier steps first." if assignment else "This journey has not been given to you."
        )
        return redirect(journey)
    StepDone.objects.get_or_create(step=current, user=request.user)
    left = [s for s in steps if not s.is_done and s.pk != current.pk]
    if left:
        return redirect("journeys:step", journey.pk, left[0].pk)
    # Only the first finish sets the time and shows the message.
    if Assignment.objects.filter(pk=assignment.pk, completed_at__isnull=True).update(completed_at=timezone.now()):
        messages.success(request, f"Well done. You have finished “{journey.title}”.")
    return redirect(journey)


# --- Pages for editors -----------------------------------------------------------


def save_journey(request, journey=None):
    form = JourneyForm(request.POST or None, request.FILES or None, instance=journey, user=request.user)
    if request.method == "POST" and form.is_valid():
        if journey is None:
            form.instance.created_by = request.user
        journey = form.save()
        if journey.is_published:  # the audience may have grown
            assign(journey, journey.audience())
        messages.success(request, "Journey saved.")
        return redirect(journey)
    context = {
        "nav": "menu",
        "form": form,
        "heading": "Edit journey" if journey else "New journey",
        "back": journey.get_absolute_url() if journey else reverse("journeys:list"),
    }
    return render(request, "journeys/form.html", context)


@permission_required("journeys.add_journey", raise_exception=True)
def new(request):
    return save_journey(request)


@editor_only
def edit(request, pk):
    return save_journey(request, get_object_or_404(Journey, pk=pk))


@permission_required("journeys.delete_journey", raise_exception=True)
@require_POST
def delete(request, pk):
    journey = get_object_or_404(Journey, pk=pk)
    audit("journey_deleted", request, journey_id=journey.pk, title=journey.title)
    journey.delete()
    messages.success(request, "Journey deleted.")
    return redirect("journeys:list")


@editor_only
@require_POST
def publish(request, pk):
    journey = get_object_or_404(Journey, pk=pk)
    # The button says which (publish=1 or 0), so a double-click or an older copy of the page can't undo it.
    publish = request.POST.get("publish") == "1"
    if publish == journey.is_published:
        return redirect(journey)  # already done
    if publish and not journey.steps.exists():
        messages.error(request, "Add at least one step before you publish.")
        return redirect(journey)
    journey.is_published = publish
    journey.save(update_fields=["is_published"])
    audit("journey_published" if journey.is_published else "journey_unpublished", request, journey_id=journey.pk)
    if journey.is_published:
        assign(journey, journey.audience())
        messages.success(request, "Published. The people it is for have been told.")
    else:
        messages.success(request, "Unpublished. Only editors can see it now.")
    return redirect(journey)


def save_step(request, step):
    form = StepForm(request.POST or None, instance=step)
    if request.method == "POST" and form.is_valid():
        new = step.pk is None
        form.save()
        if new:  # something new to do: nobody has finished until they tick it (step_done marks them finished again)
            step.journey.assignments.update(completed_at=None)
        messages.success(request, "Step saved.")
        return redirect(step.journey)
    context = {
        "nav": "menu",
        "form": form,
        "heading": "Edit step" if step.pk else "New step",
        "back": step.journey.get_absolute_url(),
    }
    return render(request, "journeys/form.html", context)


@editor_only
def step_new(request, pk):
    journey = get_object_or_404(Journey, pk=pk)
    return save_step(request, Step(journey=journey, position=journey.steps.count() + 1))


@editor_only
def step_edit(request, pk, step_pk):
    return save_step(request, get_object_or_404(Step, pk=step_pk, journey_id=pk))


@editor_only
@require_POST
def step_delete(request, pk, step_pk):
    journey = get_object_or_404(Journey, pk=pk)
    get_object_or_404(journey.steps, pk=step_pk).delete()
    # People who had only this step left have now finished.
    total = journey.steps.count()
    ticks = StepDone.objects.filter(step__journey=journey).values("user").annotate(n=Count("pk"))
    if total:
        unfinished = journey.assignments.filter(completed_at__isnull=True)
        unfinished.filter(user__in=ticks.filter(n=total).values("user")).update(completed_at=timezone.now())
    messages.success(request, "Step deleted.")
    return redirect(journey)


@editor_only
def progress(request, pk):
    journey = get_object_or_404(Journey, pk=pk)
    # shortcut: everyone on one page; fine for a few thousand people, add paging if it gets slow.
    people = journey.assignments.filter(user__is_active=True).select_related("user")
    rows = add_progress(people.order_by("user__first_name", "user__last_name"))
    context = {
        "nav": "menu",
        "journey": journey,
        "rows": rows,
        "assigned": len(rows),
        "finished": sum(1 for row in rows if row.completed_at),
    }
    return render(request, "journeys/progress.html", context)


# --- Hooks (registered in apps.py) -----------------------------------------------


def guard_cover(user, name):
    """May this person open this cover picture? Draft covers are for editors only."""
    journey = Journey.objects.filter(cover=name).first()
    return journey is not None and (journey.is_published or is_editor(user))


def search(user, q, limit):
    """Search results from the journeys given to this person."""
    found = (
        matching(Assignment.objects.filter(user=user, journey__is_published=True), q, "journey__title", "journey__description")
        .select_related("journey")[:limit]
    )
    results = []
    for a in found:
        assigned = date_format(timezone.localtime(a.assigned_at), "j F Y")
        subtitle = "Completed" if a.completed_at else f"Assigned to you on {assigned}"
        results.append((a.journey.title, a.journey.get_absolute_url(), subtitle))
    return "Journeys", results


def export(user):
    """This person's journeys for "Download my data"."""
    ticks = {}
    for tick in StepDone.objects.filter(user=user).select_related("step").order_by("done_at", "pk"):
        ticks.setdefault(tick.step.journey_id, []).append({"step": tick.step.title, "done_at": tick.done_at})
    rows = [
        {
            "title": a.journey.title,
            "assigned_at": a.assigned_at,
            "completed_at": a.completed_at,
            "steps_done": ticks.get(a.journey_id, []),
        }
        for a in Assignment.objects.filter(user=user).select_related("journey")
    ]
    return "journeys", rows, []
