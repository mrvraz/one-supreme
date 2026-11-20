from django.contrib import messages
from django.contrib.auth.decorators import permission_required
from django.core.paginator import Paginator
from django.db.models import Exists, OuterRef
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from hub.models import Notification, notify
from hub.security import LIMIT_MESSAGE, audit, over_limit

from .forms import VacancyForm
from .models import Interest, Vacancy

# Editors are people with the Django permissions jobs.add_vacancy, jobs.change_vacancy and jobs.delete_vacancy.


def can_see_interested(user, vacancy):
    """Who is interested is private: only the recruiter, whoever added the vacancy, and editors may look."""
    return user.pk in (vacancy.contact_id, vacancy.created_by_id) or user.has_perm("jobs.change_vacancy")


# --- Everyone --------------------------------------------------------------------


def vacancy_list(request):
    closed = request.GET.get("show") == "closed" and request.user.has_perm("jobs.change_vacancy")
    base = Vacancy.objects.closed() if closed else Vacancy.objects.open()
    q, location, department = (request.GET.get(key, "").strip() for key in ("q", "location", "department"))
    found = base.search(q).annotate(mine=Exists(Interest.objects.filter(vacancy=OuterRef("pk"), user=request.user)))
    if location:
        found = found.filter(location=location)
    if department:
        found = found.filter(department=department)
    context = {
        "nav": "menu",
        "closed": closed,
        "q": q,
        "location": location,
        "department": department,
        "page": Paginator(found, 30).get_page(request.GET.get("page")),
        # The two filters offer only the values in use.
        "locations": base.order_by("location").values_list("location", flat=True).distinct(),
        "departments": base.order_by("department").values_list("department", flat=True).distinct(),
    }
    return render(request, "jobs/list.html", context)


def vacancy_detail(request, pk):
    vacancy = get_object_or_404(Vacancy.objects.select_related("contact"), pk=pk)
    context = {
        "nav": "menu",
        "vacancy": vacancy,
        "mine": vacancy.interests.filter(user=request.user).first(),
        "can_see_interested": can_see_interested(request.user, vacancy),
    }
    return render(request, "jobs/detail.html", context)


@require_POST
def interest(request, pk):
    vacancy = get_object_or_404(Vacancy, pk=pk)
    if not vacancy.open_now:
        messages.error(request, "This vacancy is closed.")
    elif over_limit("interest", Interest.objects.filter(user=request.user), request):
        messages.error(request, LIMIT_MESSAGE)
    else:
        # Browsers count a line break as one character and send two, so make it one again before cutting.
        note = request.POST.get("note", "").replace("\r\n", "\n").strip()[:1000]
        _, created = Interest.objects.get_or_create(vacancy=vacancy, user=request.user, defaults={"note": note})
        if created:
            # The first of the two who still works here: an alert to someone who has left reaches nobody.
            recruiter = next((p for p in (vacancy.contact, vacancy.created_by) if p and p.is_active), None)
            url = reverse("jobs:interested", args=[pk])
            # Withdrawing and coming back must not flood the recruiter: one unread alert per person and vacancy.
            unread = Notification.objects.filter(recipient=recruiter, actor=request.user, url=url, read_at__isnull=True)
            if recruiter and not unread.exists():
                notify([recruiter], request.user, f"{request.user} is interested in {vacancy.title}", url, category="general")
            told = "The recruiter has been told" if recruiter else "HR can see"
            messages.success(request, f"Thanks. {told} you're interested.")
    return redirect(vacancy)


@require_POST
def withdraw(request, pk):
    vacancy = get_object_or_404(Vacancy, pk=pk)
    vacancy.interests.filter(user=request.user).delete()
    messages.success(request, "You've withdrawn your interest.")
    return redirect(vacancy)


def interested(request, pk):
    vacancy = get_object_or_404(Vacancy, pk=pk)
    if not can_see_interested(request.user, vacancy):
        raise Http404
    context = {"nav": "menu", "vacancy": vacancy, "interests": vacancy.interests.select_related("user")}
    return render(request, "jobs/interested.html", context)


# --- Editors ---------------------------------------------------------------------


@permission_required("jobs.add_vacancy", raise_exception=True)
def vacancy_new(request):
    form = VacancyForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.instance.created_by = request.user
        vacancy = form.save()
        audit("vacancy_published", request, vacancy_id=vacancy.pk, title=vacancy.title)
        messages.success(request, "Vacancy published.")
        return redirect(vacancy)
    return render(request, "jobs/form.html", {"nav": "menu", "form": form})


@permission_required("jobs.change_vacancy", raise_exception=True)
def vacancy_edit(request, pk):
    vacancy = get_object_or_404(Vacancy, pk=pk)
    form = VacancyForm(request.POST or None, instance=vacancy)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Changes saved.")
        return redirect(vacancy)
    return render(request, "jobs/form.html", {"nav": "menu", "form": form, "vacancy": vacancy})


@permission_required("jobs.change_vacancy", raise_exception=True)
@require_POST
def vacancy_toggle(request, pk):
    """Close an open vacancy, or reopen a closed one.

    The button says which (open=1 or 0): flipping the current state would undo a colleague's click made from an
    older copy of the page, or a double-click.
    """
    vacancy = get_object_or_404(Vacancy, pk=pk)
    reopen = request.POST.get("open") == "1"
    if reopen == vacancy.open_now:
        return redirect(vacancy)  # already done
    vacancy.is_open = reopen
    if reopen and not vacancy.open_now:  # its closing date has passed, which would keep it closed
        vacancy.closes_on = None
    vacancy.save()
    audit("vacancy_published" if reopen else "vacancy_closed", request, vacancy_id=vacancy.pk, title=vacancy.title)
    messages.success(request, "Vacancy reopened." if reopen else "Vacancy closed.")
    return redirect(vacancy)


@permission_required("jobs.delete_vacancy", raise_exception=True)
@require_POST
def vacancy_delete(request, pk):
    vacancy = get_object_or_404(Vacancy, pk=pk)
    audit("vacancy_deleted", request, vacancy_id=vacancy.pk, title=vacancy.title)
    vacancy.delete()
    messages.success(request, "Vacancy deleted.")
    return redirect("jobs:list")
