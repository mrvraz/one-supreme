from django.urls import path

from . import views

app_name = "journeys"
urlpatterns = [
    path("", views.journey_list, name="list"),
    path("new/", views.new, name="new"),
    path("<int:pk>/", views.detail, name="detail"),
    path("<int:pk>/edit/", views.edit, name="edit"),
    path("<int:pk>/delete/", views.delete, name="delete"),
    path("<int:pk>/publish/", views.publish, name="publish"),
    path("<int:pk>/progress/", views.progress, name="progress"),
    path("<int:pk>/steps/new/", views.step_new, name="step_new"),
    path("<int:pk>/steps/<int:step_pk>/", views.step_detail, name="step"),
    path("<int:pk>/steps/<int:step_pk>/done/", views.step_done, name="step_done"),
    path("<int:pk>/steps/<int:step_pk>/edit/", views.step_edit, name="step_edit"),
    path("<int:pk>/steps/<int:step_pk>/delete/", views.step_delete, name="step_delete"),
]
