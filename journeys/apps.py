from django.apps import AppConfig


class JourneysConfig(AppConfig):
    name = "journeys"
    verbose_name = "Journeys"

    def ready(self):
        from hub import plugins

        from . import views

        plugins.MENU.append((40, "Journeys", "journeys:list", "map"))
        plugins.MEDIA_GUARDS["journeys"] = views.guard_cover
        plugins.SEARCH_PROVIDERS.append(views.search)
        plugins.EXPORTERS.append(views.export)
