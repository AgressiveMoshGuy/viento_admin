import hashlib
import json
import logging
import math
import re
import time
from typing import Any
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.core.cache import cache
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from .api import GoAPIError, GoCatalogApiClient
from .form_tabs import build_tabs
from .quality import issue_label, issue_matches, summarize
from .specs import filters_by_item_id, infer_schema
from .forms import AddItemForm, EditItemForm, ItemSearchForm, SuggestFilterForm

# Сводим дублирующие ключи расхода воздуха в один фильтр.
FILTER_KEY_ALIASES: dict[str, str] = {
    "airflow_min": "airflow",
    "airflow_max": "airflow",
}


logger = logging.getLogger(__name__)


def _client() -> GoCatalogApiClient:
    return GoCatalogApiClient()


def _report_api_error(request: HttpRequest, exc: GoAPIError, action: str, not_found: "str | None" = None) -> None:
    """Показывает менеджеру понятное сообщение, а технические детали пишет в лог."""
    logger.warning("Go API: не удалось %s: %s", action, exc)
    messages.error(request, exc.explain(action, not_found))


def _canonical_filter_key(key: str) -> str:
    return FILTER_KEY_ALIASES.get(key, key)


# --- Кеш каталога -----------------------------------------------------------
# Список собирается из всего каталога (все страницы Go API), поэтому каждый клик по
# фильтру раньше заново выкачивал всё. Теперь снимок живёт 60 секунд и сбрасывается,
# когда товар создают или правят в этой админке. Чужие изменения видны через минуту,
# а ссылка «обновить» рядом со счётчиком берёт свежие данные сразу.
CATALOG_CACHE_SECONDS = 60
_VERSION_KEY = "catalog_admin:version"


def _cache_ttl() -> int:
    return int(getattr(settings, "CATALOG_CACHE_SECONDS", CATALOG_CACHE_SECONDS))


def _cache_version() -> int:
    return cache.get(_VERSION_KEY) or 1


def invalidate_catalog_cache() -> None:
    """Делает все сохранённые снимки каталога недействительными."""
    try:
        cache.incr(_VERSION_KEY)
    except ValueError:
        cache.set(_VERSION_KEY, 2, None)


def _load_catalog(client: GoCatalogApiClient, query: str, refresh: bool) -> dict[str, Any]:
    """Все товары (или результат поиска), дерево категорий и описания фильтров."""
    digest = hashlib.sha1(query.lower().encode("utf-8")).hexdigest()
    key = f"catalog_admin:{_cache_version()}:{digest}"
    if not refresh:
        cached = cache.get(key)
        if cached is not None:
            return cached

    if query:
        items = _search_all_items(client, query=query, page_size=100)
    else:
        items = _list_all_items(client, page_size=100)
    tree = client.get_catalog_tree().get("categories", [])
    snapshot = {
        "items": items,
        "tree": tree,
        "descriptions": _get_filter_descriptions(client),
        "fetched_at": time.time(),
    }
    cache.set(key, snapshot, _cache_ttl())
    return snapshot


def _list_query(cleaned: dict[str, Any], **overrides: Any) -> str:
    """Строка запроса для ссылок списка: значения кодируются, пустые пропускаются."""
    keys = ("q", "category_id", "issue", "filter_key", "filter_value", "filter_min", "filter_max", "filters_json", "sort", "limit", "page")
    data = {key: cleaned.get(key) for key in keys}
    data.update(overrides)
    return urlencode({key: value for key, value in data.items() if value not in (None, "", [])})


_CODE_CHARS = re.compile(r"^[0-9A-Za-zА-Яа-яЁё._/\-]+$")


def _code_query(raw: str) -> str | None:
    """Если запрос похож на штрихкод или артикул, возвращает его без пробелов, иначе None.

    Go ищет только по названию и описанию, а штрихкод в каталоге это SKU. Поэтому такие запросы
    мы ищем по SKU сами. Слова и короткие числа (например «100») остаются обычным поиском.
    """
    text = raw.strip()
    if not text:
        return None
    digits = text.replace(" ", "").replace("\u00a0", "").replace("-", "")
    if digits.isdigit():
        return digits if len(digits) >= 6 else None
    if re.search(r"\s", text):
        return None
    if len(text) >= 4 and re.search(r"\d", text) and _CODE_CHARS.match(text):
        return text
    return None


def _category_name(tree: list[dict[str, Any]], category_id: int | None) -> str | None:
    for node in tree:
        if node.get("id") == category_id:
            return str(node.get("name") or category_id)
        children = node.get("children") or []
        if isinstance(children, list):
            found = _category_name(children, category_id)
            if found:
                return found
    return None


def _active_conditions(
    query: str,
    category_id: int | None,
    tree: list[dict[str, Any]],
    selected_filters: list[dict[str, Any]],
    descriptions: dict[str, str],
    code: str | None = None,
    issue: str = "",
) -> list[str]:
    """Что сейчас выбрано, простыми словами: для строки «Выбрано» над списком.

    code: штрихкод или артикул, по которому реально нашли товары (иначе None).
    """
    result: list[str] = []
    if code:
        result.append(f"{'Штрихкод' if code.isdigit() else 'Артикул'}: {code}")
    elif len(query) >= 2:
        result.append(f"Поиск: «{query}»")
    if category_id:
        result.append(f"Категория: {_category_name(tree, category_id) or category_id}")
    if issue and issue_label(issue):
        result.append(f"Проблема: {issue_label(issue)}")
    for entry in selected_filters:
        key = entry["key"]
        label = descriptions.get(key) or ("Расход воздуха" if key == "airflow" else key)
        low, high = entry.get("min"), entry.get("max")
        if low is not None or high is not None:
            parts = []
            if low is not None:
                parts.append(f"от {_format_filter_number(low)}")
            if high is not None:
                parts.append(f"до {_format_filter_number(high)}")
            result.append(f"{label}: {' '.join(parts)}")
        elif str(entry.get("value", "")).strip():
            result.append(f"{label}: {entry['value']}")
    return result


def items_list(request: HttpRequest) -> HttpResponse:
    params = request.GET.copy()
    if not params:
        params = {"limit": "100", "page": "1", "sort": "name_asc"}
    form = ItemSearchForm(params)

    items: list[dict[str, Any]] = []
    total = 0
    total_pages = 0
    page = 1
    category_tree: list[dict[str, Any]] = []
    category_options: list[int] = []
    filters_tree: list[dict[str, Any]] = []
    filter_key_options: list[str] = []
    filter_value_options: list[str] = []
    filter_values_by_key: dict[str, list[str]] = {}
    selected_filter_key = ""
    selected_filter_value = ""
    selected_filter_min: float | None = None
    selected_filter_max: float | None = None
    selected_filters: list[dict[str, Any]] = []
    selected_filters_json = "[]"
    selected_issue = ""
    selected_category_id: int | None = None
    display_filter_columns: list[str] = []
    catalog_total = 0
    fetched_at: float | None = None
    load_failed = False
    short_query = False
    active_conditions: list[str] = []
    prev_query = next_query = first_query = refresh_query = ""
    found_code: str | None = None
    barcode_hit: dict[str, Any] | None = None

    if form.is_valid():
        try:
            page = form.cleaned_data["page"]
            limit = form.cleaned_data["limit"]
            query = (form.cleaned_data.get("q") or "").strip()
            api_client = _client()
            short_query = len(query) == 1

            refresh = request.GET.get("refresh") == "1"
            snapshot = None
            code = _code_query(query)
            if code:
                # Весь каталог уже в кеше, поэтому поиск по SKU не создаёт лишних запросов к Go.
                full = _load_catalog(api_client, "", refresh)
                needle = code.lower()
                matches = [item for item in full["items"] if needle in str(item.get("sku") or "").lower()]
                if matches:
                    snapshot = {**full, "items": matches}
                    found_code = code
            if snapshot is None:
                snapshot = _load_catalog(api_client, query=query if len(query) >= 2 else "", refresh=refresh)
            source_items = snapshot["items"]
            catalog_total = len(source_items)
            fetched_at = snapshot["fetched_at"]
            category_tree = snapshot["tree"]
            category_options = _collect_category_ids(category_tree)
            filter_descriptions = snapshot["descriptions"]
            selected_category_id = form.cleaned_data.get("category_id")
            category_scope_ids = _collect_category_scope_ids(category_tree, selected_category_id)
            selected_filter_key = (form.cleaned_data.get("filter_key") or "").strip()
            selected_filter_value = (form.cleaned_data.get("filter_value") or "").strip()
            selected_filter_min = form.cleaned_data.get("filter_min")
            selected_filter_max = form.cleaned_data.get("filter_max")
            selected_filters = _selected_filters(form.cleaned_data)
            selected_filters_json = json.dumps(selected_filters, ensure_ascii=False)

            items = _apply_local_filters(source_items, form.cleaned_data, category_scope_ids)
            selected_issue = form.cleaned_data.get("issue") or ""
            if selected_issue:
                items = [item for item in items if issue_matches(item, selected_issue)]
            items = _apply_sort(items, form.cleaned_data["sort"])
            total = len(items)
            total_pages = math.ceil(total / limit) if limit else 0
            page_start = (page - 1) * limit
            page_end = page_start + limit
            current_page_items = items[page_start:page_end]

            active_conditions = _active_conditions(
                query, selected_category_id, category_tree, selected_filters, filter_descriptions, found_code,
                selected_issue,
            )
            # Отсканировали штрихкод и нашёлся ровно этот товар: даём прямые ссылки на него.
            if found_code and len(items) == 1 and str(items[0].get("sku") or "").lower() == found_code.lower():
                barcode_hit = items[0]
            cleaned = form.cleaned_data
            prev_query = _list_query(cleaned, page=page - 1)
            next_query = _list_query(cleaned, page=page + 1)
            first_query = _list_query(cleaned, page=1)
            refresh_query = _list_query(cleaned, page=page, refresh=1)

            # Фасеты строим по уже отфильтрованному списку — без опций,
            # которые обнулили бы выдачу.
            filters_tree = _build_filters_tree(
                items,
                selected_filters=selected_filters,
                filter_descriptions=filter_descriptions,
            )
            filter_key_options = [node["key"] for node in filters_tree]
            filter_value_options = _filter_values_for_key(filters_tree, selected_filter_key)
            filter_values_by_key = {
                node["key"]: [entry["value"] for entry in node.get("values", [])]
                for node in filters_tree
            }
            display_filter_columns = _collect_filter_columns(items, filter_descriptions=filter_descriptions)
            items = _with_display_filters(current_page_items)
        except GoAPIError as exc:
            load_failed = True
            _report_api_error(request, exc, "загрузить список товаров")
    else:
        messages.warning(request, "Проверьте параметры фильтрации.")

    # Почему список пуст: от этого зависит, что сказать менеджеру и куда повести.
    empty_reason = ""
    if not items:
        if load_failed:
            empty_reason = "error"
        elif not form.is_valid():
            empty_reason = "invalid"
        elif total > 0:
            empty_reason = "page"  # страница за пределами выдачи
        elif active_conditions:
            empty_reason = "filtered"
        else:
            empty_reason = "empty"

    context = {
        "catalog_total": catalog_total,
        "fetched_at_label": time.strftime("%H:%M:%S", time.localtime(fetched_at)) if fetched_at else "",
        "load_failed": load_failed,
        "short_query": short_query,
        "barcode_hit": barcode_hit,
        "active_conditions": active_conditions,
        "has_conditions": bool(active_conditions),
        "selected_issue": selected_issue,
        "prev_query": prev_query,
        "next_query": next_query,
        "first_query": first_query,
        "refresh_query": refresh_query,
        "empty_reason": empty_reason,
        "form": form,
        "items": items,
        "total": total,
        "page": page,
        "total_pages": total_pages,
        "has_prev": page > 1,
        "has_next": page < total_pages,
        "prev_page": page - 1,
        "next_page": page + 1,
        "category_tree": category_tree,
        "category_options": category_options,
        "filters_tree": filters_tree,
        "filter_key_options": filter_key_options,
        "filter_value_options": filter_value_options,
        "filter_values_by_key": filter_values_by_key,
        "selected_filter_key": selected_filter_key,
        "selected_filter_value": selected_filter_value,
        "selected_filter_min": selected_filter_min,
        "selected_filter_max": selected_filter_max,
        "selected_filters_json": selected_filters_json,
        "selected_category_id": selected_category_id,
        "display_filter_columns": display_filter_columns,
        "active_nav": "items",
    }
    return render(request, "admin/catalog_admin/items_list.html", context)


def _apply_local_filters(
    items: list[dict[str, Any]],
    cleaned: dict[str, Any],
    category_scope_ids: set[int] | None = None,
) -> list[dict[str, Any]]:
    category_id = cleaned.get("category_id")
    selected_filters = _selected_filters(cleaned)

    result: list[dict[str, Any]] = []
    for item in items:
        item_category_id = int(item.get("category_id", 0))
        if category_scope_ids is not None:
            if item_category_id not in category_scope_ids:
                continue
        elif category_id and item_category_id != category_id:
            continue

        filters = _item_filters(item)
        matched = True
        for selected_filter in selected_filters:
            filter_key = selected_filter["key"]
            filter_min = selected_filter.get("min")
            filter_max = selected_filter.get("max")

            if filter_key == "airflow" and (filter_min is not None or filter_max is not None):
                bounds = _item_airflow_bounds(filters)
                if bounds is None:
                    matched = False
                    break
                item_lo, item_hi = bounds
                if filter_min is not None and item_hi < filter_min:
                    matched = False
                    break
                if filter_max is not None and item_lo > filter_max:
                    matched = False
                    break
                continue

            if filter_key not in filters:
                matched = False
                break
            current_value = filters.get(filter_key)
            if filter_min is not None or filter_max is not None:
                current_number = _parse_filter_number(current_value)
                if current_number is None:
                    matched = False
                    break
                if filter_min is not None and current_number < filter_min:
                    matched = False
                    break
                if filter_max is not None and current_number > filter_max:
                    matched = False
                    break
            else:
                filter_value = str(selected_filter.get("value", "")).strip().lower()
                if not filter_value:
                    continue
                current = str(current_value).lower()
                if filter_value not in current:
                    matched = False
                    break
        if not matched:
            continue
        result.append(item)
    return result


def _selected_filters(cleaned: dict[str, Any]) -> list[dict[str, Any]]:
    raw_filters = (cleaned.get("filters_json") or "").strip()
    if raw_filters:
        try:
            parsed = json.loads(raw_filters)
        except json.JSONDecodeError:
            parsed = []
        if isinstance(parsed, list):
            result = []
            for entry in parsed:
                normalized = _normalize_selected_filter(entry)
                if normalized:
                    result.append(normalized)
            return result

    filter_key = (cleaned.get("filter_key") or "").strip()
    if not filter_key:
        return []

    legacy_filter = {
        "key": filter_key,
        "value": (cleaned.get("filter_value") or "").strip(),
        "min": cleaned.get("filter_min"),
        "max": cleaned.get("filter_max"),
    }
    normalized = _normalize_selected_filter(legacy_filter)
    return [normalized] if normalized else []


def _normalize_selected_filter(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None

    key = _canonical_filter_key(str(value.get("key") or "").strip())
    if not key:
        return None

    min_value = _parse_filter_number(value.get("min"))
    max_value = _parse_filter_number(value.get("max"))
    if min_value is not None or max_value is not None:
        if min_value is not None and max_value is not None and min_value > max_value:
            min_value, max_value = max_value, min_value
        return {"key": key, "min": min_value, "max": max_value}

    filter_value = str(value.get("value") or "").strip()
    if not filter_value:
        return None
    return {"key": key, "value": filter_value}


def _item_airflow_bounds(filters: dict[str, Any]) -> tuple[float, float] | None:
    """Границы расхода воздуха по airflow / airflow_min / airflow_max."""
    point = _parse_filter_number(filters.get("airflow"))
    lo = _parse_filter_number(filters.get("airflow_min"))
    hi = _parse_filter_number(filters.get("airflow_max"))

    numbers = [n for n in (point, lo, hi) if n is not None]
    if not numbers:
        return None
    return min(numbers), max(numbers)


def _apply_sort(items: list[dict[str, Any]], sort: str) -> list[dict[str, Any]]:
    if sort == "name_desc":
        return sorted(items, key=lambda x: (x.get("name") or "").lower(), reverse=True)
    if sort == "price_asc":
        return sorted(items, key=lambda x: int(x.get("price") or 0))
    if sort == "price_desc":
        return sorted(items, key=lambda x: int(x.get("price") or 0), reverse=True)
    return sorted(items, key=lambda x: (x.get("name") or "").lower())


def _build_filters_tree(
    items: list[dict[str, Any]],
    selected_filters: list[dict[str, Any]] | None = None,
    filter_descriptions: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    filter_descriptions = filter_descriptions or {}
    selected_filters = selected_filters or []
    selected_values: dict[str, set[str]] = {}
    selected_ranges: dict[str, dict[str, Any]] = {}
    for selected_filter in selected_filters:
        key = _canonical_filter_key(str(selected_filter.get("key") or ""))
        if not key:
            continue
        if "value" in selected_filter:
            selected_values.setdefault(key, set()).add(str(selected_filter["value"]))
        else:
            selected_ranges[key] = selected_filter

    bucket: dict[str, dict[str, int]] = {}
    airflow_extent: list[float] = []

    for item in items:
        filters = _item_filters(item)
        seen_canonical: set[str] = set()

        for key, value in filters.items():
            # Показываем только корневые фильтры: без parent_id или с parent_id = null.
            if isinstance(value, dict) and value.get("parent_id") not in (None, ""):
                continue
            if _is_blank_filter_value(value):
                continue

            canonical = _canonical_filter_key(key)
            if canonical == "airflow":
                seen_canonical.add("airflow")
                continue

            if canonical in seen_canonical:
                continue
            seen_canonical.add(canonical)
            value_str = str(value)
            bucket.setdefault(canonical, {})
            bucket[canonical][value_str] = bucket[canonical].get(value_str, 0) + 1

        if "airflow" in seen_canonical:
            bounds = _item_airflow_bounds(filters)
            if bounds is not None:
                lo, hi = bounds
                airflow_extent.append(lo)
                if hi != lo:
                    airflow_extent.append(hi)

    if airflow_extent:
        airflow_counts: dict[str, int] = {}
        for number in airflow_extent:
            value_str = _format_filter_number(number)
            airflow_counts[value_str] = airflow_counts.get(value_str, 0) + 1
        bucket["airflow"] = airflow_counts

    tree: list[dict[str, Any]] = []
    for key in sorted(bucket.keys()):
        values = [{"value": val, "count": cnt} for val, cnt in sorted(bucket[key].items())]
        numeric_values = [_parse_filter_number(entry["value"]) for entry in values]
        is_numeric = bool(values) and all(value is not None for value in numeric_values)
        if is_numeric:
            paired_values = sorted(
                zip(values, numeric_values, strict=True),
                key=lambda entry: (entry[1], entry[0]["value"]),
            )
            values = [
                {
                    **entry,
                    "display_value": _format_filter_number(number),
                    "numeric_value": _format_filter_number(number),
                }
                for entry, number in paired_values
                if number is not None
            ]
            numeric_only = [number for _, number in paired_values if number is not None]
        else:
            numeric_only = []

        use_range_slider = is_numeric
        range_min = min(numeric_only) if numeric_only else None
        range_max = max(numeric_only) if numeric_only else None
        selected_range = selected_ranges.get(key, {})
        selected_min = selected_range.get("min")
        selected_max = selected_range.get("max")
        active_values = selected_values.get(key, set())

        label = filter_descriptions.get(key) or key
        if key == "airflow":
            label = filter_descriptions.get("airflow") or "Расход воздуха (м³/ч)"

        tree.append(
            {
                "key": key,
                "label": label,
                "values": [
                    {
                        **entry,
                        "is_active": str(entry["value"]) in active_values,
                    }
                    for entry in values
                ],
                "use_range_slider": use_range_slider,
                "range_min": _format_filter_number(range_min),
                "range_max": _format_filter_number(range_max),
                "range_step": _range_step(numeric_only),
                "selected_min": _format_filter_number(selected_min if selected_min is not None else range_min),
                "selected_max": _format_filter_number(selected_max if selected_max is not None else range_max),
                "is_active_range": key in selected_ranges,
                "is_active": key in selected_ranges or bool(active_values),
            }
        )
    return tree


def _parse_filter_number(value: Any) -> float | None:
    if isinstance(value, bool) or _is_blank_filter_value(value):
        return None
    try:
        number = float(str(value).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _is_blank_filter_value(value: Any) -> bool:
    if value in (None, "", []):
        return True
    if isinstance(value, str) and value.strip() in {"", "-", "—", "–"}:
        return True
    return False


def _format_filter_number(value: float | None) -> str:
    if value is None:
        return ""
    if value.is_integer():
        return str(int(value))
    return f"{value:g}"


def _range_step(values: list[float]) -> str:
    if values and all(value.is_integer() for value in values):
        return "1"
    return "0.01"


def _filter_values_for_key(filters_tree: list[dict[str, Any]], key: str) -> list[str]:
    if not key:
        return []
    for node in filters_tree:
        if node.get("key") == key:
            return [entry["value"] for entry in node.get("values", [])]
    return []


def _get_filter_descriptions(api_client: GoCatalogApiClient) -> dict[str, str]:
    try:
        payload = api_client.get_filter_descriptions()
    except GoAPIError as exc:
        # Описания нужны только для подписей: без них список всё равно работает.
        logger.warning("Go API: не удалось получить описания фильтров: %s", exc)
        return {}

    filters = payload.get("filters", {})
    if not isinstance(filters, dict):
        return {}
    return {
        str(key): str(value)
        for key, value in filters.items()
        if value not in (None, "")
    }


def _item_filters(item: dict[str, Any]) -> dict[str, Any]:
    raw_filters = item.get("filters")
    if isinstance(raw_filters, dict):
        return dict(raw_filters)
    return {}


def _collect_filter_columns(
    items: list[dict[str, Any]],
    max_columns: int = 8,
    filter_descriptions: dict[str, str] | None = None,
) -> list[dict[str, str]]:
    filter_descriptions = filter_descriptions or {}
    counts: dict[str, int] = {}
    for item in items:
        seen: set[str] = set()
        for key, value in _item_filters(item).items():
            if _is_blank_filter_value(value):
                continue
            canonical = _canonical_filter_key(key)
            if canonical in seen:
                continue
            seen.add(canonical)
            counts[canonical] = counts.get(canonical, 0) + 1
    ordered = sorted(counts.items(), key=lambda entry: (-entry[1], entry[0]))
    return [
        {
            "key": key,
            "label": (
                filter_descriptions.get("airflow") or "Расход воздуха (м³/ч)"
                if key == "airflow"
                else filter_descriptions.get(key) or key
            ),
        }
        for key, _ in ordered[:max_columns]
    ]


def _with_display_filters(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in items:
        display_item = dict(item)
        display_item["display_filters"] = {
            key: value
            for key, value in _item_filters(item).items()
            if not _is_blank_filter_value(value)
        }
        result.append(display_item)
    return result


def _collect_category_ids(tree: list[dict[str, Any]]) -> list[int]:
    ids: set[int] = set()

    def walk(nodes: list[dict[str, Any]]) -> None:
        for node in nodes:
            category_id = node.get("id")
            if isinstance(category_id, int):
                ids.add(category_id)
            children = node.get("children") or []
            if isinstance(children, list):
                walk(children)

    walk(tree)
    return sorted(ids)


def _collect_category_scope_ids(tree: list[dict[str, Any]], selected_category_id: int | None) -> set[int] | None:
    if not selected_category_id:
        return None

    result: set[int] = set()

    def walk(nodes: list[dict[str, Any]], matched: bool = False) -> None:
        for node in nodes:
            category_id = node.get("id")
            is_current = isinstance(category_id, int) and category_id == selected_category_id
            include = matched or is_current
            if include and isinstance(category_id, int):
                result.add(category_id)
            children = node.get("children") or []
            if isinstance(children, list):
                walk(children, include)

    walk(tree)
    if result:
        return result
    return {selected_category_id}


def _list_all_items(client: GoCatalogApiClient, page_size: int = 100) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    offset = 0
    total = None

    while total is None or offset < total:
        data = client.list_items(limit=page_size, offset=offset)
        page_items = data.get("items", []) or []
        if not isinstance(page_items, list):
            break
        items.extend(page_items)

        if total is None:
            total = int(data.get("total", 0))
        if not page_items:
            break

        offset += page_size

    return items


def _search_all_items(client: GoCatalogApiClient, query: str, page_size: int = 100) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    offset = 0
    total = None

    while total is None or offset < total:
        data = client.search_items(query=query, limit=page_size, offset=offset)
        page_items = data.get("items", []) or []
        if not isinstance(page_items, list):
            break
        items.extend(page_items)

        if total is None:
            total = int(data.get("total", 0))
        if not page_items:
            break

        offset += page_size

    return items


def quality_dashboard(request: HttpRequest) -> HttpResponse:
    summary = None
    fetched_at_label = ""
    refresh = request.GET.get("refresh") == "1"
    try:
        snapshot = _load_catalog(_client(), "", refresh)
        summary = summarize(snapshot["items"])
        fetched_at_label = time.strftime("%H:%M:%S", time.localtime(snapshot["fetched_at"]))
    except GoAPIError as exc:
        _report_api_error(request, exc, "загрузить каталог для проверки")
    if summary:
        base = {"limit": 100, "page": 1, "sort": "name_asc"}
        for row in summary["rows"]:
            row["link"] = "?" + urlencode({**base, "issue": row["key"]})
    return render(
        request,
        "admin/catalog_admin/quality.html",
        {"summary": summary, "fetched_at_label": fetched_at_label, "active_nav": "quality"},
    )


def help_page(request: HttpRequest) -> HttpResponse:
    return render(request, "admin/catalog_admin/help.html", {"active_nav": "help"})


def item_details(request: HttpRequest, sku: str) -> HttpResponse:
    item = None
    try:
        item = _client().get_item_details(sku)
    except GoAPIError as exc:
        _report_api_error(
            request, exc, "открыть карточку товара", not_found=f"Товара с артикулом «{sku}» нет в каталоге."
        )
    return render(
        request,
        "admin/catalog_admin/item_details.html",
        {"item": item, "sku": sku, "active_nav": "items"},
    )


def _specs_context(include_items: bool = False) -> dict[str, Any]:
    """Данные для редактора характеристик. Если каталог не загрузился, редактора просто нет,
    а поле со свойствами остаётся обычным текстовым."""
    try:
        snapshot = _load_catalog(_client(), "", False)
    except GoAPIError as exc:
        logger.warning("Go API: не удалось подготовить редактор характеристик: %s", exc)
        return {}
    context: dict[str, Any] = {"specs_schema": infer_schema(snapshot["items"], snapshot["descriptions"])}
    if include_items:
        context["specs_items"] = filters_by_item_id(snapshot["items"])
    return context


_COPY_FIELDS = ("name", "category_id", "description", "color", "material", "weight", "height", "width", "length", "price")


def _copy_initial(source: dict[str, Any]) -> dict[str, Any]:
    """Данные для формы «создать похожий». SKU не копируем: у нового товара он должен быть другим."""
    initial = {key: source[key] for key in _COPY_FIELDS if source.get(key) not in (None, "")}
    filters = _item_filters(source)
    if filters:
        initial["filters"] = json.dumps(filters, ensure_ascii=False, indent=2)
    return initial


def add_item(request: HttpRequest) -> HttpResponse:
    initial: dict[str, Any] = {}
    copy_sku = request.GET.get("copy_from", "").strip() if request.method == "GET" else ""
    if copy_sku:
        try:
            source = _client().get_item_details(copy_sku)
        except GoAPIError as exc:
            _report_api_error(
                request, exc, "взять данные для копии", not_found=f"Товара с артикулом «{copy_sku}» нет в каталоге."
            )
        else:
            initial = _copy_initial(source)
            if initial:
                messages.info(
                    request,
                    f"Форма заполнена по товару «{source.get('name') or copy_sku}». "
                    f"Впишите новый SKU: он должен отличаться от «{copy_sku}».",
                )
            else:
                messages.warning(request, f"Данных товара «{copy_sku}» получить не удалось. Заполните форму вручную.")
    form = AddItemForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        payload = form.cleaned_data
        try:
            _client().add_item(payload)
            invalidate_catalog_cache()
            messages.success(request, f"Товар «{payload['name']}» создан.")
            return redirect("admin:catalog_items")
        except GoAPIError as exc:
            _report_api_error(request, exc, "создать товар")

    return render(
        request,
        "admin/catalog_admin/add_item.html",
        {"form": form, "tabs": build_tabs(form), "active_nav": "add", **_specs_context()},
    )


def edit_item(request: HttpRequest) -> HttpResponse:
    initial: dict[str, Any] = {}
    item_id_param = request.GET.get("item_id")
    if item_id_param and request.method == "GET":
        try:
            initial["item_id"] = int(item_id_param)
        except ValueError:
            messages.warning(request, "Некорректный item_id в URL.")

    specs = _specs_context(include_items=True)
    current_filters = specs.get("specs_items", {}).get(str(initial.get("item_id")))
    if current_filters:
        # Go заменяет свойства целиком, поэтому начинаем с того, что у товара уже есть.
        initial["filters"] = json.dumps(current_filters, ensure_ascii=False, indent=2)

    form = EditItemForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        payload = {}
        for key, value in form.cleaned_data.items():
            if key == "item_id":
                continue
            if value not in ("", None, {}):
                payload[key] = value
        if not payload:
            messages.warning(request, "Нужно указать хотя бы одно поле для обновления.")
            return render(
                request,
                "admin/catalog_admin/edit_item.html",
                {"form": form, "tabs": build_tabs(form), "active_nav": "edit", **specs},
            )

        item_id = form.cleaned_data["item_id"]
        try:
            _client().edit_item(item_id, payload)
            invalidate_catalog_cache()
            messages.success(request, f"Товар №{item_id} обновлён.")
            return redirect("admin:catalog_items")
        except GoAPIError as exc:
            _report_api_error(
                request, exc, "сохранить изменения", not_found=f"Товара с ID {item_id} нет в каталоге."
            )

    return render(
        request,
        "admin/catalog_admin/edit_item.html",
        {"form": form, "tabs": build_tabs(form), "active_nav": "edit", **specs},
    )


def suggest_filter(request: HttpRequest) -> HttpResponse:
    form = SuggestFilterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        payload = form.cleaned_data
        try:
            _client().suggest_filter(payload)
            messages.success(request, f"Предложение фильтра «{payload['filter_label']}» отправлено.")
            return redirect("admin:filter_suggestions")
        except GoAPIError as exc:
            _report_api_error(request, exc, "отправить предложение фильтра")
    return render(
        request,
        "admin/catalog_admin/suggest_filter.html",
        {"form": form, "active_nav": "suggest"},
    )


def filter_suggestions(request: HttpRequest) -> HttpResponse:
    status = request.GET.get("status", "")
    category = request.GET.get("category", "")

    if request.method == "POST":
        suggestion_id = request.POST.get("suggestion_id")
        next_status = request.POST.get("next_status")
        if suggestion_id and next_status:
            try:
                _client().review_filter_suggestion(int(suggestion_id), next_status)
                messages.success(request, "Статус предложения обновлён.")
                return redirect("admin:filter_suggestions")
            except ValueError:
                messages.error(request, "Не удалось обновить статус предложения. Номер предложения указан неверно.")
            except GoAPIError as exc:
                _report_api_error(request, exc, "обновить статус предложения")

    suggestions: list[dict[str, Any]] = []
    try:
        data = _client().get_filter_suggestions(status=status or None, category=category or None)
        suggestions = data.get("suggestions", []) or []
    except GoAPIError as exc:
        _report_api_error(request, exc, "загрузить предложения фильтров")

    context = {
        "suggestions": suggestions,
        "status": status,
        "category": category,
        "active_nav": "moderate",
    }
    return render(request, "admin/catalog_admin/filter_suggestions.html", context)


