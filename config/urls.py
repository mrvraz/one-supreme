from django.conf import settings
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_not_required
from django.urls import include, path
from django.views.generic import RedirectView
from mozilla_django_oidc import views as oidc_views

from hub.auth import CallbackView

admin.site.site_header = f"{settings.SITE_NAME} admin"
admin.site.site_title = f"{settings.SITE_NAME} admin"
admin.site.index_title = "Moderation and settings"

urlpatterns = [
    # One sign-in page for everyone, so admins also come in through single sign-on.
    path("admin/login/", login_not_required(RedirectView.as_view(pattern_name="login", query_string=True))),
    path("admin/", admin.site.urls),
    path(
        "oidc/authenticate/",
        login_not_required(oidc_views.OIDCAuthenticationRequestView.as_view()),
        name="oidc_authentication_init",
    ),
    path(
        "oidc/callback/",
        login_not_required(CallbackView.as_view()),
        name="oidc_authentication_callback",
    ),
    path("oidc/logout/", auth_views.LogoutView.as_view(), name="oidc_logout"),
    path("chat/", include("chat.urls")),
    path("library/", include("library.urls")),
    path("journeys/", include("journeys.urls")),
    path("jobs/", include("jobs.urls")),
    path("", include("hub.urls")),
]
