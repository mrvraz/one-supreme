from django.apps import AppConfig


class HubConfig(AppConfig):
    name = "hub"
    verbose_name = "Staff hub"

    def ready(self):
        from . import security  # noqa: F401  registers sign-in/sign-out logging
