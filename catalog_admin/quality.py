"""Проверки полноты карточек для панели качества каталога.

Считаем только то, что видно по данным, которые уже отдаёт Go API. «Без фото» и «черновики»
здесь нет: в API пока нет ни фото (BACK-008…010), ни статуса товара (BACK-005, BACK-011).
Когда они появятся, достаточно добавить проверки в CHECKS.
"""

from __future__ import annotations

from typing import Any, Callable, NamedTuple


class Check(NamedTuple):
    key: str
    label: str
    hint: str
    failed: Callable[[dict[str, Any]], bool]  # True, если у товара эта проблема


def _blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _no_price(item: dict[str, Any]) -> bool:
    price = item.get("price")
    return not isinstance(price, (int, float)) or isinstance(price, bool) or price <= 0


def _no_specs(item: dict[str, Any]) -> bool:
    filters = item.get("filters")
    if not isinstance(filters, dict):
        return True
    return not any(not _blank(value) and value != [] for value in filters.values())


CHECKS: tuple[Check, ...] = (
    Check("no_price", "Без цены", "Цена не указана или равна нулю: на сайте такой товар нельзя продать.", _no_price),
    Check("no_description", "Без описания", "Описание пустое.", lambda item: _blank(item.get("description"))),
    Check("no_specs", "Без характеристик", "Нет ни одной характеристики: товар не найти через фильтры.", _no_specs),
    Check("no_sku", "Без артикула", "Не указан SKU (штрихкод): карточку не открыть по адресу и не найти сканером.", lambda item: _blank(item.get("sku"))),
    Check("no_weight", "Без веса", "Вес не указан.", lambda item: not item.get("weight")),
)

_BY_KEY = {check.key: check for check in CHECKS}


def is_valid_issue(key: str) -> bool:
    return key in _BY_KEY


def issue_label(key: str) -> str | None:
    check = _BY_KEY.get(key)
    return check.label if check else None


def issue_matches(item: dict[str, Any], key: str) -> bool:
    check = _BY_KEY.get(key)
    return bool(check and check.failed(item))


def summarize(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Количество проблем по каждой проверке и число полностью заполненных карточек."""
    total = len(items)
    rows = []
    complete = 0
    counts = {check.key: 0 for check in CHECKS}
    for item in items:
        broken = False
        for check in CHECKS:
            if check.failed(item):
                counts[check.key] += 1
                broken = True
        if not broken:
            complete += 1
    for check in CHECKS:
        count = counts[check.key]
        rows.append(
            {
                "key": check.key,
                "label": check.label,
                "hint": check.hint,
                "count": count,
                "percent": round(count * 100 / total) if total else 0,
            }
        )
    return {"total": total, "complete": complete, "rows": rows}
