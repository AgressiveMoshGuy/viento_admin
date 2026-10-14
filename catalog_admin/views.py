import json
import math
from typing import Any

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from .api import GoAPIError, GoCatalogApiClient
from .forms import AddItemForm, EditItemForm, ItemSearchForm, SuggestFilterForm

# Сводим дублирующие ключи расхода воздуха в один фильтр.
FILTER_KEY_ALIASES: dict[str, str] = {
    "airflow_min": "airflow",
    "airflow_max": "airflow",
}


def _client() -> GoCatalogApiClient:
    return GoCatalogApiClient()


def _canonical_filter_key(key: str) -> str:
    return FILTER_KEY_ALIASES.get(key, key)


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
    selected_category_id: int | None = None
    display_filter_columns: list[str] = []

    if form.is_valid():
        try:
            page = form.cleaned_data["page"]
            limit = form.cleaned_data["limit"]
            query = (form.cleaned_data.get("q") or "").strip()
            api_client = _client()

            if len(query) >= 2:
                source_items = _search_all_items(api_client, query=query, page_size=max(100, limit))
            else:
                source_items = _list_all_items(api_client, page_size=max(100, limit))

            tree_payload = api_client.get_catalog_tree()
            category_tree = tree_payload.get("categories", [])
            category_options = _collect_category_ids(category_tree)
            filter_descriptions = _get_filter_descriptions(api_client)
            selected_category_id = form.cleaned_data.get("category_id")
            category_scope_ids = _collect_category_scope_ids(category_tree, selected_category_id)
            selected_filter_key = (form.cleaned_data.get("filter_key") or "").strip()
            selected_filter_value = (form.cleaned_data.get("filter_value") or "").strip()
            selected_filter_min = form.cleaned_data.get("filter_min")
            selected_filter_max = form.cleaned_data.get("filter_max")
            selected_filters = _selected_filters(form.cleaned_data)
            selected_filters_json = json.dumps(selected_filters, ensure_ascii=False)

            items = _apply_local_filters(source_items, form.cleaned_data, category_scope_ids)
            items = _apply_sort(items, form.cleaned_data["sort"])
            total = len(items)
            total_pages = math.ceil(total / limit) if limit else 0
            page_start = (page - 1) * limit
            page_end = page_start + limit
            current_page_items = items[page_start:page_end]

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
            messages.error(request, str(exc))
    else:
        messages.warning(request, "Проверьте параметры фильтрации.")

    context = {
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
    except GoAPIError:
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


def item_details(request: HttpRequest, sku: str) -> HttpResponse:
    item = None
    try:
        item = _client().get_item_details(sku)
    except GoAPIError as exc:
        messages.error(request, str(exc))
    return render(
        request,
        "admin/catalog_admin/item_details.html",
        {"item": item, "sku": sku, "active_nav": "items"},
    )


def add_item(request: HttpRequest) -> HttpResponse:
    form = AddItemForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        payload = form.cleaned_data
        try:
            response = _client().add_item(payload)
            messages.success(request, f"Товар создан: {response}")
            return redirect("admin:catalog_items")
        except GoAPIError as exc:
            messages.error(request, str(exc))

    return render(
        request,
        "admin/catalog_admin/add_item.html",
        {"form": form, "active_nav": "add"},
    )


def edit_item(request: HttpRequest) -> HttpResponse:
    initial: dict[str, Any] = {}
    item_id_param = request.GET.get("item_id")
    if item_id_param and request.method == "GET":
        try:
            initial["item_id"] = int(item_id_param)
        except ValueError:
            messages.warning(request, "Некорректный item_id в URL.")

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
                {"form": form, "active_nav": "edit"},
            )

        try:
            response = _client().edit_item(form.cleaned_data["item_id"], payload)
            messages.success(request, f"Товар обновлен: {response}")
            return redirect("admin:catalog_items")
        except GoAPIError as exc:
            messages.error(request, str(exc))

    return render(
        request,
        "admin/catalog_admin/edit_item.html",
        {"form": form, "active_nav": "edit"},
    )


def suggest_filter(request: HttpRequest) -> HttpResponse:
    form = SuggestFilterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        payload = form.cleaned_data
        try:
            response = _client().suggest_filter(payload)
            messages.success(request, f"Предложение фильтра создано: {response}")
            return redirect("admin:filter_suggestions")
        except GoAPIError as exc:
            messages.error(request, str(exc))
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
                messages.success(request, "Статус предложения обновлен.")
                return redirect("admin:filter_suggestions")
            except (ValueError, GoAPIError) as exc:
                messages.error(request, str(exc))

    suggestions: list[dict[str, Any]] = []
    try:
        data = _client().get_filter_suggestions(status=status or None, category=category or None)
        suggestions = data.get("suggestions", []) or []
    except GoAPIError as exc:
        messages.error(request, str(exc))

    context = {
        "suggestions": suggestions,
        "status": status,
        "category": category,
        "active_nav": "moderate",
    }
    return render(request, "admin/catalog_admin/filter_suggestions.html", context)


