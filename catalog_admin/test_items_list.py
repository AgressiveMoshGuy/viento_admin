import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase

from .api import GoAPIError
from .errors import KIND_CONNECTION, KIND_HTTP
from .views import _code_query, _list_query


def make_items(count=3, name="Вентилятор"):
    return [
        {
            "id": index,
            "sku": f"SKU-{index}",
            "name": f"{name} {index}",
            "category_id": 1,
            "price": 1000 * index,
            "description": "",
            "filters": {"diameter": 100 if index % 2 else 125},
        }
        for index in range(1, count + 1)
    ]


class FakeClient:
    """Подставляется вместо клиента Go API и считает обращения."""

    def __init__(self, items=None, fail=False):
        self.items = items if items is not None else make_items()
        self.fail = fail
        self.calls = {"list": 0, "search": 0, "tree": 0, "descriptions": 0, "add": 0}

    def _maybe_fail(self):
        if self.fail:
            raise GoAPIError("down", kind=KIND_CONNECTION, detail="refused")

    def list_items(self, limit=20, offset=0):
        self.calls["list"] += 1
        self._maybe_fail()
        return {"items": self.items[offset : offset + limit], "total": len(self.items)}

    def search_items(self, query, limit=20, offset=0):
        self.calls["search"] += 1
        self._maybe_fail()
        hits = [item for item in self.items if query.lower() in item["name"].lower()]
        return {"items": hits[offset : offset + limit], "total": len(hits)}

    def get_item_details(self, sku):
        for item in self.items:
            if item["sku"] == sku:
                return item
        raise GoAPIError("not found", kind=KIND_HTTP, status=404, detail="")

    def get_catalog_tree(self):
        self.calls["tree"] += 1
        return {"categories": [{"id": 1, "name": "Вентиляторы осевые", "children": []}]}

    def get_filter_descriptions(self):
        self.calls["descriptions"] += 1
        return {"filters": {"diameter": "Диаметр"}}

    def add_item(self, payload):
        self.calls["add"] += 1
        return {}


class ListQueryTests(SimpleTestCase):
    def test_encodes_values_and_skips_empty(self):
        query = _list_query({"q": "a b&c", "limit": 50, "page": None, "sort": ""}, page=2)
        self.assertEqual(query, "q=a+b%26c&limit=50&page=2")


class CodeQueryTests(SimpleTestCase):
    def test_barcode_digits(self):
        self.assertEqual(_code_query("4627117123581"), "4627117123581")

    def test_spaces_and_hyphens_are_removed_from_digits(self):
        self.assertEqual(_code_query(" 4627 1171-23581 "), "4627117123581")

    def test_short_numbers_stay_text_search(self):
        for text in ("100", "12345", "ва"):
            with self.subTest(text=text):
                self.assertIsNone(_code_query(text))

    def test_article_with_digit(self):
        self.assertEqual(_code_query("VNT-103"), "VNT-103")
        self.assertEqual(_code_query("100СВ"), "100СВ")

    def test_words_and_phrases_stay_text_search(self):
        for text in ("вентилятор", "вентилятор 100", "осевой вытяжной", ""):
            with self.subTest(text=text):
                self.assertIsNone(_code_query(text))


class BarcodeSearchTests(TestCase):
    EAN = ["4627117123581", "4627117128753", "4627117128760"]

    def setUp(self):
        cache.clear()
        user = get_user_model().objects.create_superuser(username="tester")
        self.client.force_login(user)
        items = make_items(3)
        for item, ean in zip(items, self.EAN):
            item["sku"] = ean
        self.fake = FakeClient(items)
        patcher = patch("catalog_admin.views._client", return_value=self.fake)
        patcher.start()
        self.addCleanup(patcher.stop)

    def get(self, q):
        return self.client.get("/catalog/", {"q": q, "limit": 100, "page": 1, "sort": "name_asc"})

    def test_exact_barcode_finds_item_without_go_text_search(self):
        response = self.get("4627117128753")
        self.assertContains(response, "Найдено товаров: <strong>1</strong>")
        self.assertContains(response, "Штрихкод: 4627117128753")
        self.assertContains(response, "Найден по штрихкоду:")
        self.assertContains(response, "/catalog/items/4627117128753/")
        self.assertContains(response, "item_id=2")
        self.assertEqual(self.fake.calls["search"], 0)

    def test_partial_barcode_lists_all_matches_without_banner(self):
        response = self.get("4627117128")
        self.assertContains(response, "Найдено товаров: <strong>2</strong>")
        self.assertContains(response, "Штрихкод: 4627117128")
        self.assertNotContains(response, "Найден по штрихкоду:")

    def test_barcode_with_spaces(self):
        response = self.get("4627 1171 23581")
        self.assertContains(response, "Штрихкод: 4627117123581")

    def test_article_with_letters(self):
        for item in self.fake.items:
            item["sku"] = "VNT-" + item["sku"][-3:]
        response = self.get("vnt-753")
        self.assertContains(response, "Артикул: vnt-753")
        self.assertContains(response, "Найден по штрихкоду:")

    def test_unknown_code_falls_back_to_text_search(self):
        response = self.get("9999999999999")
        self.assertEqual(self.fake.calls["search"], 1)
        self.assertContains(response, "Ничего не найдено.")
        self.assertContains(response, "Поиск: «9999999999999»")

    def test_plain_word_does_not_load_whole_catalog(self):
        self.get("Вентилятор")
        self.assertEqual(self.fake.calls["list"], 0)
        self.assertEqual(self.fake.calls["search"], 1)

    def test_barcode_reuses_cached_catalog(self):
        self.client.get("/catalog/", {"limit": 100, "page": 1, "sort": "name_asc"})
        self.get("4627117123581")
        self.assertEqual(self.fake.calls["list"], 1)

    def test_search_field_hints_at_barcode(self):
        response = self.get("")
        self.assertContains(response, "Название, штрихкод или артикул")


class ItemsListPageTests(TestCase):
    def setUp(self):
        cache.clear()
        user = get_user_model().objects.create_superuser(username="tester")
        self.client.force_login(user)
        self.fake = FakeClient()
        patcher = patch("catalog_admin.views._client", return_value=self.fake)
        patcher.start()
        self.addCleanup(patcher.stop)

    def get(self, query=""):
        return self.client.get("/catalog/" + query)

    def test_counter_without_conditions(self):
        response = self.get("?limit=100&page=1&sort=name_asc")
        self.assertContains(response, "Товаров в каталоге: <strong>3</strong>", html=False)

    def test_search_shows_condition_chip_and_reset(self):
        response = self.get("?q=Вентилятор+2&limit=100&page=1&sort=name_asc")
        self.assertContains(response, "Найдено товаров: <strong>1</strong>")
        self.assertNotContains(response, "из 1")
        self.assertContains(response, "Поиск: «Вентилятор 2»")
        self.assertContains(response, "Сбросить всё")

    def test_category_and_filter_conditions_in_plain_words(self):
        filters = json.dumps([{"key": "diameter", "value": "100"}])
        response = self.get(f"?category_id=1&filters_json={filters}&limit=100&page=1&sort=name_asc")
        self.assertContains(response, "Категория: Вентиляторы осевые")
        self.assertContains(response, "Диаметр: 100")
        self.assertContains(response, "Найдено товаров: <strong>2</strong> из 3")

    def test_empty_search_result(self):
        response = self.get("?q=ничего+нет&limit=100&page=1&sort=name_asc")
        self.assertContains(response, "Ничего не найдено.")
        self.assertNotContains(response, "В каталоге пока нет товаров")

    def test_empty_catalog(self):
        self.fake.items = []
        response = self.get("?limit=100&page=1&sort=name_asc")
        self.assertContains(response, "В каталоге пока нет товаров.")
        self.assertContains(response, "Добавить первый товар")

    def test_server_error_does_not_pretend_catalog_is_empty(self):
        self.fake.fail = True
        response = self.get("?limit=100&page=1&sort=name_asc")
        self.assertContains(response, "Список не загружен.")
        self.assertContains(response, "Не удаётся связаться с сервером каталога")
        self.assertNotContains(response, "Товары не найдены")
        self.assertNotContains(response, "Товаров в каталоге")

    def test_one_letter_search_explains_itself(self):
        response = self.get("?q=в&limit=100&page=1&sort=name_asc")
        self.assertContains(response, "Поиск работает от двух символов")

    def test_pagination_links_keep_special_characters(self):
        self.fake.items = make_items(3, name="A&B")
        response = self.get("?q=A%26B&limit=1&page=1&sort=name_asc")
        self.assertContains(response, "Страница 1 из 3")
        self.assertContains(response, "q=A%26B")
        self.assertContains(response, "page=2")
        self.assertNotContains(response, "← Предыдущая")

    def test_page_beyond_results(self):
        response = self.get("?limit=1&page=9&sort=name_asc")
        self.assertContains(response, "На этой странице товаров нет.")
        self.assertContains(response, "Вернуться к первой странице")

    def test_snapshot_is_reused_between_requests(self):
        self.get("?limit=100&page=1&sort=name_asc")
        self.get("?limit=100&page=1&sort=price_desc")
        self.assertEqual(self.fake.calls["list"], 1)
        self.assertEqual(self.fake.calls["tree"], 1)

    def test_refresh_link_fetches_fresh_data(self):
        self.get("?limit=100&page=1&sort=name_asc")
        self.get("?limit=100&page=1&sort=name_asc&refresh=1")
        self.assertEqual(self.fake.calls["list"], 2)

    def test_creating_item_invalidates_snapshot(self):
        self.get("?limit=100&page=1&sort=name_asc")
        response = self.client.post(
            "/catalog/items/add/",
            {"name": "Новый", "category_id": 1, "price": 100},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.fake.calls["add"], 1)
        self.get("?limit=100&page=1&sort=name_asc")
        self.assertEqual(self.fake.calls["list"], 2)

    def test_failed_load_is_not_cached(self):
        self.fake.fail = True
        self.get("?limit=100&page=1&sort=name_asc")
        self.fake.fail = False
        response = self.get("?limit=100&page=1&sort=name_asc")
        self.assertContains(response, "Товаров в каталоге: <strong>3</strong>")
