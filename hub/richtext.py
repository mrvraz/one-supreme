"""Turns the light formatting people type into safe HTML.

Supported: **bold**, *italic*, ~~strikethrough~~, lines starting with "- " (bullets) or "1. " (numbers),
links, and @mentions of the people passed in. Every piece of typed text is escaped before any tag is added,
so HTML typed by a user never reaches the page as HTML.
"""

import re

from django.utils.html import escape
from django.utils.safestring import mark_safe

URL = re.compile(r"""(https?://[^\s<>"']*[^\s<>"'.,;:!?)\]])""")
BOLD = re.compile(r"\*\*(\S(?:.*?\S)?)\*\*")
ITALIC = re.compile(r"(?<![*\w])\*(\S(?:.*?\S)?)\*(?![*\w])")
STRIKE = re.compile(r"~~(\S(?:.*?\S)?)~~")
BULLET = re.compile(r"^\s*[-•]\s+(.+)$")
NUMBER = re.compile(r"^\s*\d{1,3}[.)]\s+(.+)$")


def _inline(raw, mentions):
    out = []
    for i, part in enumerate(URL.split(raw)):
        safe = escape(part)
        if i % 2:  # a web address: only http and https ever match, so no script links
            out.append(f'<a href="{safe}" target="_blank" rel="noopener noreferrer">{safe}</a>')
            continue
        safe = BOLD.sub(r"<strong>\1</strong>", safe)
        safe = ITALIC.sub(r"<em>\1</em>", safe)
        safe = STRIKE.sub(r"<del>\1</del>", safe)
        for person in mentions:
            name = escape(f"@{person}")
            safe = safe.replace(name, f'<a class="mention" href="{escape(person.get_absolute_url())}">{name}</a>')
        out.append(safe)
    return "".join(out)


def render(text, mentions=()):
    """Return `text` as safe HTML. `mentions` are the people whose "@Full Name" becomes a profile link."""
    mentions = sorted(mentions, key=lambda person: -len(str(person)))  # longest names first
    html, paragraph, open_list = [], [], None

    def close_paragraph():
        if paragraph:
            html.append("<p>" + "<br>".join(paragraph) + "</p>")
            paragraph.clear()

    def close_list():
        nonlocal open_list
        if open_list:
            html.append(f"</{open_list}>")
            open_list = None

    for line in (text or "").replace("\r\n", "\n").split("\n"):
        bullet, number = BULLET.match(line), NUMBER.match(line)
        if bullet or number:
            tag = "ul" if bullet else "ol"
            close_paragraph()
            if open_list != tag:
                close_list()
                html.append(f"<{tag}>")
                open_list = tag
            html.append("<li>" + _inline((bullet or number).group(1), mentions) + "</li>")
        elif not line.strip():
            close_paragraph()
            close_list()
        else:
            close_list()
            paragraph.append(_inline(line, mentions))
    close_paragraph()
    close_list()
    return mark_safe("".join(html))


def plain(text):
    """The text without formatting marks, for previews and notifications."""
    text = re.sub(r"\*\*|~~", "", text or "")
    return re.sub(r"(?<![*\w])\*(\S(?:.*?\S)?)\*(?![*\w])", r"\1", text)
