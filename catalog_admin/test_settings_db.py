import importlib.util
import os
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase

SETTINGS = Path(__file__).resolve().parent.parent / "config" / "settings.py"


def load_settings(env):
    """Читает config/settings.py заново с заданным окружением, не трогая настройки запущенных тестов."""
    spec = importlib.util.spec_from_file_location("settings_under_test", SETTINGS)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(os.environ, env, clear=False):
        os.environ.pop("ADMIN_DB_PATH", None) if "ADMIN_DB_PATH" not in env else None
        spec.loader.exec_module(module)
    return module


class DatabaseSettingsTests(SimpleTestCase):
    def test_sqlite_file_next_to_project_by_default(self):
        db = load_settings({}).DATABASES["default"]
        self.assertEqual(db["ENGINE"], "django.db.backends.sqlite3")
        self.assertTrue(str(db["NAME"]).endswith("db.sqlite3"))

    def test_path_can_point_to_docker_volume(self):
        db = load_settings({"ADMIN_DB_PATH": "/data/db.sqlite3"}).DATABASES["default"]
        self.assertEqual(db["ENGINE"], "django.db.backends.sqlite3")
        self.assertEqual(db["NAME"], "/data/db.sqlite3")

    def test_empty_path_falls_back_to_default(self):
        db = load_settings({"ADMIN_DB_PATH": ""}).DATABASES["default"]
        self.assertTrue(str(db["NAME"]).endswith("db.sqlite3"))
