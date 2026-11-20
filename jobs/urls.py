from django.urls import path

from . import views

app_name = "jobs"
urlpatterns = [
    path("", views.vacancy_list, name="list"),
    path("new/", views.vacancy_new, name="new"),
    path("<int:pk>/", views.vacancy_detail, name="detail"),
    path("<int:pk>/edit/", views.vacancy_edit, name="edit"),
    path("<int:pk>/toggle/", views.vacancy_toggle, name="toggle"),
    path("<int:pk>/delete/", views.vacancy_delete, name="delete"),
    path("<int:pk>/interest/", views.interest, name="interest"),
    path("<int:pk>/withdraw/", views.withdraw, name="withdraw"),
    path("<int:pk>/interested/", views.interested, name="interested"),
]
