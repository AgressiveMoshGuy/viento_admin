import json
import unittest

from .errors import (
    KIND_CONNECTION,
    KIND_HTTP,
    KIND_TIMEOUT,
    ApiFailure,
    describe_json_error,
    explain,
    reason,
)


class ReasonTests(unittest.TestCase):
    def test_server_down(self):
        text = reason(ApiFailure(KIND_CONNECTION, detail="Connection refused"))
        self.assertIn("связаться", text)

    def test_timeout(self):
        text = reason(ApiFailure(KIND_TIMEOUT, detail="Read timed out"))
        self.assertIn("долго не отвечает", text)

    def test_status_codes(self):
        cases = {
            400: "не принял данные",
            401: "ключ доступа",
            403: "нет прав",
            404: "нет",
            409: "уже существует",
            422: "не прошли проверку",
            429: "Слишком много",
        }
        for status, expected in cases.items():
            with self.subTest(status=status):
                self.assertIn(expected, reason(ApiFailure(KIND_HTTP, status, "x")))

    def test_server_error_does_not_leak_details(self):
        text = reason(ApiFailure(KIND_HTTP, 500, "pq: relation items does not exist"))
        self.assertIn("На сервере каталога произошла ошибка", text)
        self.assertNotIn("relation", text)

    def test_hint_beats_status_for_duplicate_sku(self):
        failure = ApiFailure(KIND_HTTP, 500, 'pq: duplicate key value violates unique constraint "items_sku_key"')
        self.assertIn("артикулом (SKU) уже есть", reason(failure))

    def test_json_type_error_from_go(self):
        failure = ApiFailure(KIND_HTTP, 400, "json: cannot unmarshal string into Go struct field .price of type int")
        self.assertIn("не того типа", reason(failure))

    def test_custom_not_found(self):
        failure = ApiFailure(KIND_HTTP, 404, "not found")
        self.assertEqual(reason(failure, not_found="Товар не найден."), "Товар не найден.")

    def test_unknown_status(self):
        self.assertIn("неожиданно", reason(ApiFailure(KIND_HTTP, 302, "")))


class ExplainTests(unittest.TestCase):
    def test_includes_action_and_code(self):
        text = explain("сохранить товар", ApiFailure(KIND_HTTP, 409, "dup"))
        self.assertTrue(text.startswith("Не удалось сохранить товар."))
        self.assertTrue(text.endswith("(код ошибки 409)"))

    def test_no_code_when_server_did_not_answer(self):
        text = explain("открыть товар", ApiFailure(KIND_CONNECTION))
        self.assertNotIn("код ошибки", text)


class JsonErrorTests(unittest.TestCase):
    def test_points_to_position(self):
        with self.assertRaises(json.JSONDecodeError) as ctx:
            json.loads('{"a": 1,}')
        text = describe_json_error(ctx.exception)
        self.assertIn("строке 1", text)
        self.assertNotIn("Expecting", text)


if __name__ == "__main__":
    unittest.main()
