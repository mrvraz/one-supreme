from django.urls import path

from . import views

app_name = "library"
urlpatterns = [
    path("files/", views.files, name="files"),
    path("files/upload/", views.upload, name="upload"),
    path("files/folders/new/", views.folder_new, name="folder_new"),
    path("files/folders/<int:pk>/delete/", views.folder_delete, name="folder_delete"),
    path("files/<int:pk>/delete/", views.document_delete, name="document_delete"),
    path("files/<int:pk>/feature/", views.document_feature, name="document_feature"),
    path("featured/", views.featured, name="featured"),
    path("featured/links/new/", views.link_new, name="link_new"),
    path("featured/links/<int:pk>/delete/", views.link_delete, name="link_delete"),
    # hub's group pages link to these two names; keep the names and the <slug> argument.
    path("groups/<slug:slug>/files/", views.group_files, name="group_files"),
    path("groups/<slug:slug>/featured/", views.group_featured, name="group_featured"),
    path("kb/", views.kb, name="kb"),
    path("kb/new/", views.article_new, name="article_new"),
    path("kb/categories/new/", views.category_new, name="category_new"),
    path("kb/<int:pk>/", views.article, name="article"),
    path("kb/<int:pk>/edit/", views.article_edit, name="article_edit"),
    path("kb/<int:pk>/delete/", views.article_delete, name="article_delete"),
    path("legal/", views.legal, name="legal"),
]
