import json
from unittest.mock import patch

from django.test import SimpleTestCase

from .specs import filters_by_item_id, infer_schema
from .test_item_form import FakeApiTestCase


def schema_by_key(items, descriptions=None):
    return {entry["key"]: entry for entry in infer_schema(items, descriptions or {})}


class InferSchemaTests(SimpleTestCase):
    def test_types_follow_existing_values(self):
        items = [
            {"filters": {"diameter": 100, "timer": True, "material": "plastic", "color": "white"}},
            {"filters": {"diameter": 125.5, "timer": False, "material": "zinc", "color": "white"}},
        ]
        schema = schema_by_key(items)
        self.assertEqual(schema["diameter"]["type"], "number")
        self.assertEqual(schema["timer"]["type"], "bool")
        self.assertEqual(schema["material"]["type"], "enum")
        self.assertEqual(schema["color"]["options"], ["white"])

    def test_bool_is_not_mistaken_for_number(self):
        self.assertEqual(schema_by_key([{"filters": {"a": True}}])["a"]["type"], "bool")

    def test_numeric_strings_stay_text_so_data_is_not_retyped(self):
        schema = schema_by_key([{"filters": {"phases": "3"}}, {"filters": {"phases": "1"}}])
        self.assertEqual(schema["phases"]["type"], "enum")

    def test_mixed_values_are_text(self):
        schema = schema_by_key([{"filters": {"x": 1}}, {"filters": {"x": "много"}}])
        self.assertEqual(schema["x"]["type"], "text")

    def test_nested_values_are_raw(self):
        schema = schema_by_key([{"filters": {"x": {"parent_id": 3}}}])
        self.assertEqual(schema["x"]["type"], "raw")

    def test_many_distinct_strings_become_free_text(self):
        items = [{"filters": {"series": f"S{n}"}} for n in range(30)]
        self.assertEqual(schema_by_key(items)["series"]["type"], "text")

    def test_options_are_sorted_by_popularity(self):
        items = [{"filters": {"color": value}} for value in ("a", "b", "b", "b", "c", "c")]
        self.assertEqual(schema_by_key(items)["color"]["options"], ["b", "c", "a"])

    def test_blank_values_are_ignored(self):
        schema = schema_by_key([{"filters": {"x": ""}}, {"filters": {"x": 5}}, {"filters": {"x": None}}])
        self.assertEqual(schema["x"]["type"], "number")

    def test_described_key_without_data_uses_unit_in_label(self):
        schema = schema_by_key([], {"voltage": "Напряжение (В)", "bearing": "Подшипник"})
        self.assertEqual(schema["voltage"]["type"], "number")
        self.assertEqual(schema["bearing"]["type"], "text")
        self.assertEqual(schema["voltage"]["label"], "Напряжение (В)")

    def test_key_without_description_is_labelled_by_its_name(self):
        self.assertEqual(schema_by_key([{"filters": {"mystery": 1}}])["mystery"]["label"], "mystery")

    def test_items_without_filters_do_not_break(self):
        self.assertEqual(infer_schema([{}, {"filters": None}, {"filters": []}], {}), [])

    def test_sorted_by_label(self):
        schema = infer_schema([], {"b": "Ящик", "a": "Арка"})
        self.assertEqual([entry["label"] for entry in schema], ["Арка", "Ящик"])


class FiltersByIdTests(SimpleTestCase):
    def test_maps_only_items_with_filters(self):
        items = [{"id": 1, "filters": {"a": 1}}, {"id": 2, "filters": {}}, {"id": 3}]
        self.assertEqual(filters_by_item_id(items), {"1": {"a": 1}})


class SpecsEditorPageTests(FakeApiTestCase):
    def setUp(self):
        super().setUp()
        for item in self.fake.items:
            item["filters"] = {"diameter": 100, "timer": True}

    def test_add_page_embeds_schema(self):
        response = self.client.get("/catalog/items/add/")
        self.assertContains(response, 'id="specs-schema"')
        self.assertContains(response, "specs_editor.js")
        self.assertNotContains(response, 'id="specs-items"')
        schema = {entry["key"]: entry["type"] for entry in response.context["specs_schema"]}
        self.assertEqual(schema, {"diameter": "number", "timer": "bool"})

    def test_edit_prefills_current_filters_of_chosen_item(self):
        response = self.client.get("/catalog/items/edit/?item_id=2")
        self.assertContains(response, "&quot;diameter&quot;: 100")
        self.assertContains(response, 'id="specs-items"')

    def test_edit_without_item_has_no_prefill(self):
        response = self.client.get("/catalog/items/edit/")
        self.assertNotContains(response, "&quot;diameter&quot;")
        self.assertContains(response, 'id="specs-items"')

    def test_page_still_works_when_catalog_is_unavailable(self):
        self.fake.fail = True
        response = self.client.get("/catalog/items/add/")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "specs_editor.js")
        self.assertContains(response, 'id="id_filters"')

    def test_posted_json_is_what_gets_saved(self):
        payload = json.dumps({"diameter": 125, "timer": False})
        with patch.object(self.fake, "add_item", wraps=self.fake.add_item) as add:
            response = self.client.post(
                "/catalog/items/add/",
                {"name": "Новый", "category_id": 1, "price": 100, "filters": payload},
            )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(add.call_args[0][0]["filters"], {"diameter": 125, "timer": False})
