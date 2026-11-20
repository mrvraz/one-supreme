from django import template

from hub import richtext

register = template.Library()


@register.filter
def rich(text):
    """Formatted, safely escaped text. For posts and comments with mentions use `.body_html` instead."""
    return richtext.render(text)


@register.filter
def plain(text):
    return richtext.plain(text)


@register.filter
def lookup(mapping, key):
    """`{{ mapping|lookup:key }}` for dictionaries with variable keys."""
    return mapping.get(key) if mapping else None


@register.simple_tag(takes_context=True)
def query(context, **changes):
    """The current query string with some values replaced: `?{% query sort='activity' page=None %}`."""
    params = context["request"].GET.copy()
    for key, value in changes.items():
        params.pop(key, None)
        if value not in (None, ""):
            params[key] = value
    return params.urlencode()
