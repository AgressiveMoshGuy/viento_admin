"""Разбивка формы товара по вкладкам.

Одна и та же раскладка нужна и для создания, и для правки товара, поэтому она живёт здесь,
а не в шаблонах. Вкладки «Фото» и «SEO» пока без полей: в Go API для них ничего нет
(BACK-008, BACK-005), и на вкладке честно написано, что это появится позже.
"""

from __future__ import annotations

from typing import Any

# (id вкладки, название, поля формы по порядку, заметка для пустой вкладки)
TABS: tuple[tuple[str, str, tuple[str, ...], str], ...] = (
    (
        "main",
        "Основное",
        ("item_id", "name", "sku", "category_id", "category_slug", "price", "description"),
        "",
    ),
    (
        "specs",
        "Характеристики",
        ("filters", "color", "material", "weight", "height", "width", "length"),
        "",
    ),
    (
        "photos",
        "Фото",
        (),
        "Загрузка фото пока недоступна, она появится позже. Пока фото к товару добавить нельзя.",
    ),
    (
        "seo",
        "SEO",
        (),
        "Адрес страницы, заголовок и описание для поисковиков появятся позже. Сейчас их заполнить нельзя.",
    ),
)

FULL_WIDTH_FIELDS = frozenset({"description", "filters"})


def build_tabs(form: Any) -> list[dict[str, Any]]:
    """Возвращает вкладки с полями формы. Открыта будет первая вкладка с ошибкой, иначе первая."""
    known = set(TABS_FIELD_NAMES)
    unplaced = [name for name in form.fields if name not in known]
    tabs: list[dict[str, Any]] = []
    for tab_id, label, names, note in TABS:
        names = list(names)
        if tab_id == "main":
            names += unplaced  # поле, которого нет в раскладке, не должно пропасть
        fields = [form[name] for name in names if name in form.fields]
        tabs.append(
            {
                "id": tab_id,
                "label": label,
                "fields": fields,
                "note": note,
                "error_count": sum(1 for field in fields if field.errors),
                "full": FULL_WIDTH_FIELDS,
            }
        )

    active = next((tab for tab in tabs if tab["error_count"]), tabs[0])
    for tab in tabs:
        tab["active"] = tab is active
    return tabs


TABS_FIELD_NAMES = tuple(name for _, _, names, _ in TABS for name in names)
