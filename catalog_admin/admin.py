from django.contrib import admin
from django.shortcuts import redirect
from django.urls import path

from . import views

_original_get_urls = admin.site.get_urls


def _get_urls():
    urls = _original_get_urls()
    custom_urls = [
        # Список товаров — корневой экран каталога
        path("catalog/", admin.site.admin_view(views.items_list), name="catalog_items"),
        # Старый URL редиректим на /catalog/
        path(
            "catalog/items/",
            admin.site.admin_view(lambda request: redirect("admin:catalog_items", permanent=False)),
            name="catalog_items_legacy",
        ),
        # add/edit до <sku>, иначе «add»/«edit» перехватятся как sku
        path("catalog/items/add/", admin.site.admin_view(views.add_item), name="catalog_add_item"),
        path("catalog/items/edit/", admin.site.admin_view(views.edit_item), name="catalog_edit_item"),
        path(
            "catalog/items/<str:sku>/",
            admin.site.admin_view(views.item_details),
            name="catalog_item_details",
        ),
        path(
            "catalog/filters/suggest/",
            admin.site.admin_view(views.suggest_filter),
            name="suggest_filter",
        ),
        path(
            "catalog/filters/suggestions/",
            admin.site.admin_view(views.filter_suggestions),
            name="filter_suggestions",
        ),
        # Шпаргалка для менеджера
        path("catalog/help/", admin.site.admin_view(views.help_page), name="catalog_help"),
        path("catalog/quality/", admin.site.admin_view(views.quality_dashboard), name="catalog_quality"),
    ]
    return custom_urls + urls


admin.site.get_urls = _get_urls
admin.site.site_header = "Каталог Viento"
admin.site.site_title = "Каталог Viento"
admin.site.index_title = "Управление каталогом"
admin.site.index_template = "admin/catalog_admin/custom_index.html"
