from django.contrib.auth import get_user_model
from django.test import TestCase

SECTIONS = ("find", "card", "add", "edit", "filters", "errors", "limits")


class HelpPageTests(TestCase):
    def test_requires_login(self):
        response = self.client.get("/catalog/help/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response["Location"])

    def test_staff_sees_help_page(self):
        user = get_user_model().objects.create_superuser(username="tester")
        self.client.force_login(user)
        response = self.client.get("/catalog/help/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Как работать с каталогом")
        for section in SECTIONS:
            with self.subTest(section=section):
                self.assertContains(response, f'id="{section}"')

    def test_nav_has_help_link_on_other_pages(self):
        user = get_user_model().objects.create_superuser(username="tester")
        self.client.force_login(user)
        # форма добавления не обращается к Go API, поэтому подходит для проверки меню
        response = self.client.get("/catalog/items/add/")
        self.assertContains(response, 'href="/catalog/help/"')
