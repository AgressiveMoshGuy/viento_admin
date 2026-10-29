from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase

from .form_tabs import build_tabs
from .forms import AddItemForm, EditItemForm
from .test_items_list import FakeClient


class BuildTabsTests(TestCase):
    def test_every_field_lands_on_exactly_one_tab(self):
        for form in (AddItemForm(), EditItemForm()):
            placed = [field.name for tab in build_tabs(form) for field in tab["fields"]]
            self.assertCountEqual(placed, list(form.fields))

    def test_first_tab_is_open_without_errors(self):
        tabs = build_tabs(AddItemForm())
        self.assertEqual([tab["active"] for tab in tabs], [True, False, False, False])

    def test_tab_with_error_is_open_and_counted(self):
        form = AddItemForm({"name": "Вентилятор", "category_id": 1, "price": 100, "filters": "{oops"})
        tabs = {tab["id"]: tab for tab in build_tabs(form)}
        self.assertTrue(tabs["specs"]["active"])
        self.assertFalse(tabs["main"]["active"])
        self.assertEqual(tabs["specs"]["error_count"], 1)

    def test_photo_and_seo_tabs_explain_they_are_not_ready(self):
        tabs = {tab["id"]: tab for tab in build_tabs(AddItemForm())}
        for tab_id in ("photos", "seo"):
            self.assertEqual(tabs[tab_id]["fields"], [])
            self.assertIn("позже", tabs[tab_id]["note"])


class FakeApiTestCase(TestCase):
    def setUp(self):
        cache.clear()
        user = get_user_model().objects.create_superuser(username="tester")
        self.client.force_login(user)
        self.fake = FakeClient()
        patcher = patch("catalog_admin.views._client", return_value=self.fake)
        patcher.start()
        self.addCleanup(patcher.stop)


class ItemFormPageTests(FakeApiTestCase):

    def test_add_page_shows_four_tabs(self):
        response = self.client.get("/catalog/items/add/")
        for label in ("Основное", "Характеристики", "Фото", "SEO"):
            self.assertContains(response, f"{label}")
        self.assertContains(response, 'data-panel="specs"')
        self.assertContains(response, "item_form_tabs.js")

    def test_edit_page_keeps_item_id_from_url(self):
        response = self.client.get("/catalog/items/edit/?item_id=7")
        self.assertContains(response, 'value="7"')

    def test_invalid_json_reopens_specs_tab(self):
        response = self.client.post(
            "/catalog/items/add/",
            {"name": "Новый", "category_id": 1, "price": 100, "filters": "{oops"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'aria-selected="true"')
        html = response.content.decode()
        specs_button = html[html.index('id="tab-specs"') : html.index('data-tab="specs"')]
        self.assertIn('aria-selected="true"', specs_button)
        self.assertContains(response, "Свойства записаны неверно")
        self.assertEqual(self.fake.calls["add"], 0)

    def test_create_still_works_through_tabs(self):
        response = self.client.post(
            "/catalog/items/add/",
            {"name": "Новый", "category_id": 1, "price": 100, "color": "белый"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.fake.calls["add"], 1)


class CopyItemTests(FakeApiTestCase):
    def setUp(self):
        super().setUp()
        self.fake.items[0]["sku"] = "4627117123581"
        self.fake.items[0]["filters"] = {"diameter": 100, "color": "белый"}
        self.fake.items[0]["color"] = "серый"

    def test_form_is_prefilled_from_existing_item(self):
        response = self.client.get("/catalog/items/add/?copy_from=4627117123581")
        self.assertContains(response, 'value="Вентилятор 1"')
        self.assertContains(response, 'value="серый"')
        self.assertContains(response, "&quot;diameter&quot;: 100")
        self.assertContains(response, "Впишите новый SKU")

    def test_sku_is_not_copied(self):
        response = self.client.get("/catalog/items/add/?copy_from=4627117123581")
        html = response.content.decode()
        sku_input = html[html.index('name="sku"') : html.index('name="sku"') + 120]
        self.assertNotIn('value="4627117123581"', sku_input)

    def test_unknown_sku_shows_message_and_empty_form(self):
        response = self.client.get("/catalog/items/add/?copy_from=nope")
        self.assertContains(response, "Товара с артикулом «nope» нет в каталоге.")
        self.assertNotContains(response, "Впишите новый SKU")

    def test_copy_links_in_list_and_card(self):
        self.assertContains(
            self.client.get("/catalog/?limit=100&page=1&sort=name_asc"),
            "copy_from=4627117123581",
        )
        self.assertContains(self.client.get("/catalog/items/4627117123581/"), "copy_from=4627117123581")

    def test_empty_and_missing_fields_are_not_copied(self):
        from .views import _copy_initial

        initial = _copy_initial({"name": "A", "color": "", "weight": None, "filters": {}, "price": 0})
        self.assertEqual(initial, {"name": "A", "price": 0})

    def test_empty_answer_from_api_does_not_claim_form_was_filled(self):
        self.fake.items[0]["name"] = ""
        self.fake.items[0].update(category_id=None, price=None, filters={}, description="", color="")
        response = self.client.get("/catalog/items/add/?copy_from=4627117123581")
        self.assertContains(response, "получить не удалось")
        self.assertNotContains(response, "Форма заполнена")


class PhotoPlaceholderTests(FakeApiTestCase):
    def test_card_shows_big_placeholder(self):
        self.fake.items[0]["sku"] = "4627117123581"
        response = self.client.get("/catalog/items/4627117123581/")
        self.assertContains(response, "catalog-photo--lg")
        self.assertContains(response, "Нет фото")

    def test_missing_item_has_no_placeholder(self):
        response = self.client.get("/catalog/items/nope/")
        self.assertNotContains(response, "catalog-photo")

    def test_list_has_small_placeholder_in_hidden_photo_column(self):
        response = self.client.get("/catalog/?limit=100&page=1&sort=name_asc")
        self.assertContains(response, "catalog-photo--sm", count=len(self.fake.items))
        html = response.content.decode()
        self.assertIn('class="catalog-col catalog-col-hidden" data-col-id="photo"', html)
        picker = html[html.index('data-col-id="photo"') : html.index('data-col-id="photo"') + 80]
        self.assertNotIn("checked", picker)
