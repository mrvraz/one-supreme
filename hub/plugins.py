"""Hooks that let the other apps (chat, library, journeys, jobs) plug into shared pages.

Each app fills these from its AppConfig.ready(), so `hub` never has to import them.
"""

# Top folder under MEDIA_ROOT -> function(user, name) -> bool. May this person open this uploaded file?
# A folder with no guard is never served.
MEDIA_GUARDS = {}

# function(user, q, limit) -> (section label, [(title, url, subtitle), ...]) for the search page.
SEARCH_PROVIDERS = []

# function(user) -> (key, data for my-data.json, [paths of files to include]) for "Download my data".
EXPORTERS = []

# function(now) -> (label, number removed), run by the nightly clean-up.
PURGERS = []

# (position, label, url name, icon name) rows on the Menu page. hub's own rows use positions 10, 20, 30…
MENU = []

# Tab name ("chat") -> function(user) -> number shown as a red badge on that tab.
NAV_BADGES = {}
