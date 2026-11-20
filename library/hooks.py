"""What the library adds to hub's shared pages. Registered in apps.py."""

import os

from .files import download_name
from .models import Article, Document


def media_guard(user, name):
    """May this person download this library file? Returns its download name and id, or False."""
    doc = Document.objects.filter(file=name).select_related("community").first()
    if doc is None or (doc.community and not doc.community.can_view(user)):
        return False
    return {"name": download_name(doc.original_name) or os.path.basename(name), "document_id": doc.pk}


def search_files(user, q, limit):
    docs = Document.objects.viewable_by(user).search(q).select_related("community")[:limit]
    return "Files", [(d.title, d.file.url, f"{d.original_name} · {d.community or 'Company'}") for d in docs]


def search_kb(user, q, limit):
    articles = Article.objects.search(q).select_related("category")[:limit]
    return "Knowledge base", [(a.title, a.get_absolute_url(), a.category.name) for a in articles]


def export(user):
    """For "Download my data": what this person added. The files themselves belong to the company and stay out."""
    data = {
        "documents": list(
            Document.objects.filter(uploaded_by=user).values("title", "original_name", "size", "created_at", "community__name")
        ),
        "articles": list(Article.objects.filter(created_by=user).values("title", "category__name", "created_at", "updated_at")),
    }
    return "library", data, []
