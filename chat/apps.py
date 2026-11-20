from datetime import timedelta

from django.apps import AppConfig


class ChatConfig(AppConfig):
    name = "chat"
    verbose_name = "Chat"

    def ready(self):
        from hub import plugins, security

        from . import hooks

        security.LIMITS["message"] = (300, timedelta(hours=1))
        plugins.NAV_BADGES["chat"] = hooks.unread_chats
        plugins.MEDIA_GUARDS["chat"] = hooks.can_open_picture
        plugins.EXPORTERS.append(hooks.export)
        plugins.PURGERS.append(hooks.purge)
