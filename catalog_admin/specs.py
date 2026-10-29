"""Типы характеристик для редактора свойств товара.

Go API хранит свойства как «ключ: значение» и не говорит, какого типа ключ. Проверяет он только,
что ключ есть в таблице фильтров. Поэтому тип мы определяем по тому, какие значения у этого ключа
уже стоят у товаров каталога. Это временное решение, пока в API нет списка фильтров с типами
(BACK-034): когда он появится, достаточно заменить `infer_schema`.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

TYPE_BOOL = "bool"
TYPE_NUMBER = "number"
TYPE_ENUM = "enum"
TYPE_TEXT = "text"
TYPE_RAW = "raw"  # вложенные значения: редактору не по силам, сохраняем как есть

MAX_ENUM_OPTIONS = 15
_UNIT_IN_LABEL = re.compile(r"\([^)]*\)\s*$")  # «Диаметр (мм)»: единица измерения в скобках


def _is_blank(value: Any) -> bool:
    if value in (None, "", []):
        return True
    return isinstance(value, str) and value.strip() in {"", "-", "—", "–"}


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _kind_of(values: list[Any], label: str) -> str:
    if not values:
        # Данных нет: единица измерения в названии подсказывает число, иначе просто текст.
        return TYPE_NUMBER if _UNIT_IN_LABEL.search(label) else TYPE_TEXT
    if any(isinstance(value, (dict, list)) for value in values):
        return TYPE_RAW
    if all(isinstance(value, bool) for value in values):
        return TYPE_BOOL
    if all(_is_number(value) for value in values):
        return TYPE_NUMBER
    if all(isinstance(value, str) for value in values):
        return TYPE_ENUM if len(set(values)) <= MAX_ENUM_OPTIONS else TYPE_TEXT
    return TYPE_TEXT  # смесь типов: не навязываем число и не ломаем значения


def infer_schema(items: list[dict[str, Any]], descriptions: dict[str, str]) -> list[dict[str, Any]]:
    """Список характеристик: key, label, type и (для списков значений) options.

    В списке есть все ключи из описаний фильтров (их Go считает допустимыми) и все ключи,
    которые встретились у товаров.
    """
    seen: dict[str, list[Any]] = {}
    for item in items:
        filters = item.get("filters")
        if not isinstance(filters, dict):
            continue
        for key, value in filters.items():
            bucket = seen.setdefault(str(key), [])
            if not _is_blank(value):
                bucket.append(value)

    keys = set(descriptions) | set(seen)
    schema = []
    for key in keys:
        label = descriptions.get(key) or key
        values = seen.get(key, [])
        kind = _kind_of(values, label)
        entry: dict[str, Any] = {"key": key, "label": label, "type": kind}
        if kind == TYPE_ENUM:
            counts = Counter(values)
            entry["options"] = [value for value, _ in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))]
        schema.append(entry)
    schema.sort(key=lambda entry: entry["label"].lower())
    return schema


def filters_by_item_id(items: list[dict[str, Any]], limit: int = 3000) -> dict[str, dict[str, Any]]:
    """Свойства товаров по их id, чтобы форма правки подставила текущие значения.

    Go при правке заменяет свойства целиком, поэтому редактор обязан начинать с того, что уже есть.
    """
    result: dict[str, dict[str, Any]] = {}
    for item in items[:limit]:
        item_id = item.get("id")
        filters = item.get("filters")
        if item_id is not None and isinstance(filters, dict) and filters:
            result[str(item_id)] = filters
    return result
