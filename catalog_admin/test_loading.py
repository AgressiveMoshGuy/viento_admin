from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.test import TestCase


class LoadingScriptTests(TestCase):
    def test_static_file_exists(self):
        self.assertIsNotNone(finders.find("catalog_admin/loading.js"))

    def test_script_is_included_on_catalog_pages(self):
        user = get_user_model().objects.create_superuser(username="tester")
        self.client.force_login(user)
        # форма добавления не обращается к Go API, поэтому подходит для проверки
        response = self.client.get("/catalog/items/add/")
        self.assertContains(response, "catalog_admin/loading.js")
        self.assertContains(response, "catalog-entity-form")
