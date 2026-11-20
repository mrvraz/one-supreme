from datetime import timedelta

from django.apps import AppConfig


class LibraryConfig(AppConfig):
    name = "library"
    verbose_name = "Library"

    def ready(self):
        from hub import plugins
        from hub.security import LIMITS

        from . import hooks

        LIMITS["document"] = (50, timedelta(days=1))
        plugins.MEDIA_GUARDS["library"] = hooks.media_guard
        plugins.MENU += [
            (30, "Knowledge base", "library:kb", "book"),
            (50, "Featured", "library:featured", "star"),
            (70, "Files", "library:files", "folder"),
        ]
        plugins.SEARCH_PROVIDERS += [hooks.search_files, hooks.search_kb]
        plugins.EXPORTERS.append(hooks.export)
