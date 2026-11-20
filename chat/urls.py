from django.urls import path

from . import views

app_name = "chat"
urlpatterns = [
    path("", views.chat_list, name="list"),
    path("new/", views.new, name="new"),
    path("with/<int:user_id>/", views.with_person, name="with"),
    path("<int:pk>/", views.thread, name="thread"),
    path("<int:pk>/send/", views.send, name="send"),
    path("<int:pk>/new/", views.poll, name="poll"),
    path("<int:pk>/mute/", views.mute, name="mute"),
    path("<int:pk>/leave/", views.leave, name="leave"),
    path("<int:pk>/members/", views.members, name="members"),
    path("messages/<int:pk>/delete/", views.delete_message, name="delete_message"),
    path("messages/<int:pk>/report/", views.report, name="report"),
]
