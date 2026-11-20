"""Pages of the library: files, featured links and files, and the knowledge base."""

import os

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import permission_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from hub.models import Community
from hub.security import LIMIT_MESSAGE, audit, over_limit
from hub.views import safe_redirect

from .files import ALLOWED, MAX_MB, check_document
from .models import Article, Category, Document, FeaturedLink, Folder

# --- Who may do what ---------------------------------------------------------------

# Template flag -> the Django permission it needs for company-wide items.
RIGHTS = {
    "can_add": "add_document",
    "can_add_folder": "add_folder",
    "can_delete": "delete_document",
    "can_delete_folder": "delete_folder",
    "can_feature": "add_featuredlink",
}


def may(user, community, permission):
    """Company-wide items need the Django permission. Inside a group or unit, its admins decide."""
    return community.is_admin(user) if community else user.has_perm(f"library.{permission}")


def _rights(user, community):
    """Every RIGHTS flag for this person in this scope, for the templates."""
    if community:
        return dict.fromkeys(RIGHTS, community.is_admin(user))
    return {flag: may(user, None, permission) for flag, permission in RIGHTS.items()}


def _require(user, community, permission):
    """Stop unless this person may do this here. A group they can't see doesn't exist for them."""
    if community and not community.can_view(user):
        raise Http404
    if not may(user, community, permission):
        raise PermissionDenied


def _visible_community(user, slug):
    community = get_object_or_404(Community, slug=slug)
    if not community.can_view(user):
        raise Http404
    return community


def _folder(params, community):
    """The folder named in the query string or form. It must belong to this scope."""
    pk = params.get("folder", "")
    return get_object_or_404(Folder, pk=pk, community=community) if pk.isdecimal() else None


def _target(request, permission):
    """Where a form wants to add something: (community or None, folder or None), once the person is allowed."""
    slug = request.POST.get("community")
    community = get_object_or_404(Community, slug=slug) if slug else None
    _require(request.user, community, permission)
    return community, _folder(request.POST, community)


def _files_url(community, folder=None):
    url = reverse("library:group_files", args=[community.slug]) if community else reverse("library:files")
    return f"{url}?folder={folder.pk}" if folder else url


def _featured_url(community):
    return reverse("library:group_featured", args=[community.slug]) if community else reverse("library:featured")


# --- Files -------------------------------------------------------------------------


def _browse(request, community):
    """The folders and files of one scope: the whole company (community is None) or one group or unit."""
    q = request.GET.get("q", "").strip()
    folder = _folder(request.GET, community)
    docs = Document.objects.filter(community=community).select_related("uploaded_by")
    context = {
        "nav": "menu",
        "tab": "company",
        "group": community,
        "folder": folder,
        "q": q,
        "crumbs": folder.path() if folder else [],
        # shortcut: no paging, and a search shows the first 100 matches; add paging if folders pass a few hundred files.
        "folders": [] if q else Folder.objects.filter(community=community, parent=folder),
        "docs": docs.search(q)[:100] if q else docs.filter(folder=folder),
        "accept": ",".join(sorted(ALLOWED)),
        "max_mb": MAX_MB,
        **_rights(request.user, community),
    }
    return render(request, "library/files.html", context)


def files(request):
    tab, q = request.GET.get("tab"), request.GET.get("q", "").strip()
    if tab == "groups":
        context = {"groups": request.user.communities.all()}
    elif tab == "recent":
        docs = Document.objects.viewable_by(request.user).search(q).select_related("uploaded_by", "community")
        context = {"docs": docs.order_by("-created_at")[:50], "q": q}
    else:
        return _browse(request, None)
    return render(request, "library/files.html", {"nav": "menu", "tab": tab, **context})


def group_files(request, slug):
    return _browse(request, _visible_community(request.user, slug))


@require_POST
def upload(request):
    community, folder = _target(request, "add_document")
    file = request.FILES.get("file")
    if file is None:
        messages.error(request, "Choose a file to add.")
    elif over_limit("document", Document.objects.filter(uploaded_by=request.user), request):
        messages.error(request, LIMIT_MESSAGE)
    else:
        original = file.name
        try:
            check_document(file)
        except ValidationError as error:
            messages.error(request, error.messages[0])
        else:
            doc = Document.objects.create(
                folder=folder,
                community=community,
                title=request.POST.get("title", "").strip()[:200] or os.path.splitext(original)[0][:200],
                file=file,
                original_name=original,
                size=file.size,
                uploaded_by=request.user,
            )
            audit("document_uploaded", request, document_id=doc.pk, name=original)
            messages.success(request, "File added.")
    return redirect(_files_url(community, folder))


@require_POST
def folder_new(request):
    community, parent = _target(request, "add_folder")
    name = request.POST.get("name", "").strip()[:120]
    if name:
        Folder.objects.create(name=name, parent=parent, community=community, created_by=request.user)
        messages.success(request, "Folder created.")
    else:
        messages.error(request, "Give the folder a name.")
    return redirect(_files_url(community, parent))


@require_POST
def folder_delete(request, pk):
    folder = get_object_or_404(Folder, pk=pk)
    _require(request.user, folder.community, "delete_folder")
    if folder.children.exists() or folder.documents.exists():
        messages.error(request, "Only empty folders can be deleted. Delete what's inside first.")
        return redirect(_files_url(folder.community, folder))
    audit("folder_deleted", request, folder_id=folder.pk, name=folder.name)
    folder.delete()
    messages.success(request, "Folder deleted.")
    return redirect(_files_url(folder.community, folder.parent))


@require_POST
def document_delete(request, pk):
    doc = get_object_or_404(Document, pk=pk)
    _require(request.user, doc.community, "delete_document")
    audit("document_deleted", request, document_id=doc.pk, name=doc.original_name)
    doc.delete()  # the file goes with it (see models)
    messages.success(request, "File deleted.")
    return redirect(_files_url(doc.community, doc.folder))


# --- Featured ----------------------------------------------------------------------


def _featured(request, community):
    context = {
        "nav": "menu",
        "group": community,
        "links": FeaturedLink.objects.filter(community=community),
        "docs": Document.objects.filter(community=community, is_featured=True).select_related("uploaded_by"),
        "can_feature": may(request.user, community, "add_featuredlink"),
    }
    return render(request, "library/featured.html", context)


def featured(request):
    return _featured(request, None)


def group_featured(request, slug):
    return _featured(request, _visible_community(request.user, slug))


@require_POST
def link_new(request):
    community, _ = _target(request, "add_featuredlink")
    link = FeaturedLink(
        title=request.POST.get("title", "").strip(),
        url=request.POST.get("url", "").strip(),
        community=community,
        created_by=request.user,
    )
    try:
        link.full_clean()
    except ValidationError:
        messages.error(request, "Add a title and a web address that starts with http:// or https://.")
    else:
        link.save()
        messages.success(request, "Link added.")
    return redirect(_featured_url(community))


@require_POST
def link_delete(request, pk):
    link = get_object_or_404(FeaturedLink, pk=pk)
    _require(request.user, link.community, "add_featuredlink")
    link.delete()
    messages.success(request, "Link removed.")
    return redirect(_featured_url(link.community))


@require_POST
def document_feature(request, pk):
    doc = get_object_or_404(Document, pk=pk)
    _require(request.user, doc.community, "add_featuredlink")
    doc.is_featured = request.POST.get("featured") == "1"
    doc.save(update_fields=["is_featured"])
    messages.success(request, "Added to Featured." if doc.is_featured else "Removed from Featured.")
    return safe_redirect(request, request.META.get("HTTP_REFERER", ""), _featured_url(doc.community))


# --- Knowledge base ----------------------------------------------------------------


class ArticleForm(forms.ModelForm):
    class Meta:
        model = Article
        fields = ["category", "title", "body", "is_legal"]
        widgets = {"body": forms.Textarea(attrs={"rows": 14})}


def kb(request):
    q = request.GET.get("q", "").strip()
    context = {"nav": "menu", "q": q, "has_categories": Category.objects.exists()}
    if q:
        context["results"] = Article.objects.search(q).select_related("category")
    elif Article.objects.exists():
        context["categories"] = Category.objects.prefetch_related("articles")
    else:
        context["empty"] = True
    return render(request, "library/kb.html", context)


def legal(request):
    return render(request, "library/legal.html", {"nav": "menu", "articles": Article.objects.filter(is_legal=True)})


def article(request, pk):
    found = get_object_or_404(Article.objects.select_related("category"), pk=pk)
    return render(request, "library/article.html", {"nav": "menu", "article": found})


def _edit_article(request, existing):
    form = ArticleForm(request.POST or None, instance=existing)
    if request.method == "POST" and form.is_valid():
        if existing is None:
            form.instance.created_by = request.user
        form.instance.updated_by = request.user
        saved = form.save()
        messages.success(request, "Article saved.")
        return redirect(saved)
    return render(request, "library/article_form.html", {"nav": "menu", "form": form, "article": existing})


@permission_required("library.add_article", raise_exception=True)
def article_new(request):
    return _edit_article(request, None)


@permission_required("library.change_article", raise_exception=True)
def article_edit(request, pk):
    return _edit_article(request, get_object_or_404(Article, pk=pk))


@require_POST
@permission_required("library.delete_article", raise_exception=True)
def article_delete(request, pk):
    found = get_object_or_404(Article, pk=pk)
    audit("article_deleted", request, article_id=found.pk, title=found.title)
    found.delete()
    messages.success(request, "Article deleted.")
    return redirect("library:kb")


@require_POST
@permission_required("library.add_article", raise_exception=True)
def category_new(request):
    name = request.POST.get("name", "").strip()[:120]
    if name:
        Category.objects.get_or_create(name=name)
        messages.success(request, "Category added.")
    else:
        messages.error(request, "Give the category a name.")
    return redirect("library:kb")
