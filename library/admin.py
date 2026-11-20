"""Order categories and featured links here (the "position" field), and tidy articles.

Folders and files are left out on purpose: files must go through the upload page, which checks them.
"""

from django.contrib import admin

from .models import Article, Category, FeaturedLink

admin.site.register(Category, list_display=("name", "position"), list_editable=("position",))
admin.site.register(FeaturedLink, list_display=("title", "community", "position"), list_editable=("position",))
admin.site.register(Article, list_display=("title", "category", "is_legal", "updated_at"), search_fields=("title", "body"))
