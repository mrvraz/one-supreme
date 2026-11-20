from django.conf import settings
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_not_required
from django.core.exceptions import PermissionDenied
from django.urls import include, path
from django.views.generic import RedirectView
from mozilla_django_oidc import views as oidc_views

admin.site.site_header = f"{settings.SITE_NAME} admin"
admin.site.site_title = f"{settings.SITE_NAME} admin"
admin.site.index_title = "Moderation and settings"
to_sign_in = RedirectView.as_view(pattern_name="login", query_string=True)


@login_not_required
def admin_login(request):
    """One sign-in page for everyone, so admins also come in through single sign-on."""
    if request.user.is_authenticated and not request.user.is_staff:
        raise PermissionDenied  # signed in without admin rights: the sign-in page would send them straight back here
    return to_sign_in(request)


urlpatterns = [
    path("admin/login/", admin_login, name="admin_login"),
    path("admin/", admin.site.urls),
    path(
        "oidc/authenticate/",
        login_not_required(oidc_views.OIDCAuthenticationRequestView.as_view()),
        name="oidc_authentication_init",
    ),
    path(
        "oidc/callback/",
        login_not_required(oidc_views.OIDCAuthenticationCallbackView.as_view()),
        name="oidc_authentication_callback",
    ),
    path("oidc/logout/", auth_views.LogoutView.as_view(), name="oidc_logout"),
    path("chat/", include("chat.urls")),
    path("library/", include("library.urls")),
    path("journeys/", include("journeys.urls")),
    path("jobs/", include("jobs.urls")),
    path("", include("hub.urls")),
]
