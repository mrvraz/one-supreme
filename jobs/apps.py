from datetime import timedelta

from django.apps import AppConfig


class JobsConfig(AppConfig):
    name = "jobs"
    verbose_name = "Jobs"

    def ready(self):
        from hub import plugins, security

        from . import hooks

        # One person can say they're interested in 20 vacancies a day: plenty for real use, no good for flooding recruiters.
        security.LIMITS["interest"] = (20, timedelta(days=1))
        plugins.MENU.append((20, "Jobs", "jobs:list", "briefcase"))
        plugins.SEARCH_PROVIDERS.append(hooks.search)
        plugins.EXPORTERS.append(hooks.export)
        plugins.PURGERS.append(hooks.purge)
