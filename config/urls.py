from django.contrib import admin
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.urls import path


urlpatterns = [
    # Админка на корне домена (для Traefik path: /), не на /admin/
    path("", admin.site.urls),
]

urlpatterns += staticfiles_urlpatterns()
