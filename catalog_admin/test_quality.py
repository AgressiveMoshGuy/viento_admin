from django.test import SimpleTestCase

from .quality import CHECKS, is_valid_issue, issue_label, issue_matches, summarize
from .test_item_form import FakeApiTestCase
from .test_items_list import make_items


def full_item(**overrides):
    item = {"id": 1, "sku": "4627117123503", "name": "Вентилятор", "category_id": 1, "price": 100000,
            "description": "Осевой", "weight": 0.5, "filters": {"diameter": 100}}
    item.update(overrides)
    return item


class ChecksTests(SimpleTestCase):
    def test_complete_item_has_no_problems(self):
        self.assertFalse(any(check.failed(full_item()) for check in CHECKS))

    def test_each_problem_is_detected(self):
        cases = {
            "no_price": full_item(price=0),
            "no_description": full_item(description="  "),
            "no_specs": full_item(filters={}),
            "no_sku": full_item(sku=None),
            "no_weight": full_item(weight=None),
        }
        for key, item in cases.items():
            with self.subTest(key=key):
                self.assertTrue(issue_matches(item, key))
                others = [k for k in cases if k != key]
                self.assertFalse(any(issue_matches(item, other) for other in others))

    def test_price_none_or_negative_or_bool_counts_as_missing(self):
        for price in (None, -5, True, "100"):
            with self.subTest(price=price):
                self.assertTrue(issue_matches(full_item(price=price), "no_price"))

    def test_specs_with_only_blank_values_count_as_missing(self):
        self.assertTrue(issue_matches(full_item(filters={"a": "", "b": None, "c": []}), "no_specs"))
        self.assertTrue(issue_matches(full_item(filters=None), "no_specs"))
        self.assertFalse(issue_matches(full_item(filters={"timer": False}), "no_specs"))

    def test_unknown_issue_is_not_valid_and_matches_nothing(self):
        self.assertFalse(is_valid_issue("bogus"))
        self.assertFalse(issue_matches(full_item(price=0), "bogus"))
        self.assertIsNone(issue_label("bogus"))

    def test_summary_counts_and_complete(self):
        items = [full_item(), full_item(price=0), full_item(price=0, description="")]
        summary = summarize(items)
        by_key = {row["key"]: row for row in summary["rows"]}
        self.assertEqual(summary["total"], 3)
        self.assertEqual(summary["complete"], 1)
        self.assertEqual(by_key["no_price"]["count"], 2)
        self.assertEqual(by_key["no_price"]["percent"], 67)
        self.assertEqual(by_key["no_description"]["count"], 1)

    def test_summary_of_empty_catalog(self):
        summary = summarize([])
        self.assertEqual((summary["total"], summary["complete"]), (0, 0))
        self.assertTrue(all(row["count"] == 0 and row["percent"] == 0 for row in summary["rows"]))


class QualityPageTests(FakeApiTestCase):
    def setUp(self):
        super().setUp()
        self.fake.items = make_items(4)
        self.fake.items[0]["price"] = 0
        self.fake.items[1]["price"] = 0
        self.fake.items[2]["filters"] = {}

    def test_dashboard_shows_counts_and_links(self):
        response = self.client.get("/catalog/quality/")
        self.assertContains(response, "Качество каталога")
        summary = response.context["summary"]
        by_key = {row["key"]: row for row in summary["rows"]}
        self.assertEqual(by_key["no_price"]["count"], 2)
        self.assertEqual(by_key["no_specs"]["count"], 1)
        self.assertContains(response, "issue=no_price")
        self.assertContains(response, "Без фото")
        self.assertContains(response, "Появится, когда на сервере")

    def test_clean_check_says_all_good_and_has_no_link(self):
        response = self.client.get("/catalog/quality/")
        self.assertContains(response, "Здесь всё в порядке.")
        self.assertNotContains(response, "issue=no_sku")

    def test_list_filters_by_issue_and_explains_it(self):
        response = self.client.get("/catalog/?issue=no_price&limit=100&page=1&sort=name_asc")
        self.assertContains(response, "Проблема: Без цены")
        self.assertContains(response, "Найдено товаров: <strong>2</strong> из 4")
        self.assertContains(response, 'name="issue" id="id_issue_hidden" value="no_price"')

    def test_unknown_issue_is_rejected_by_the_form(self):
        response = self.client.get("/catalog/?issue=bogus&limit=100&page=1&sort=name_asc")
        self.assertContains(response, "Проверьте параметры")

    def test_pagination_keeps_issue(self):
        response = self.client.get("/catalog/?issue=no_price&limit=1&page=1&sort=name_asc")
        self.assertContains(response, "issue=no_price")

    def test_dashboard_survives_api_failure(self):
        self.fake.fail = True
        response = self.client.get("/catalog/quality/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Проверка не выполнена.")
        self.assertNotContains(response, "Полностью заполнено")

    def test_nav_has_quality_link(self):
        self.assertContains(self.client.get("/catalog/help/"), "Качество каталога")
