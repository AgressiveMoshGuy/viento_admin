from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse, urlunparse

import requests
from django.conf import settings

from .errors import KIND_CONNECTION, KIND_HTTP, KIND_TIMEOUT, ApiFailure, explain


class GoAPIError(Exception):
    """Ошибка обращения к Go API.

    str(exc) остаётся техническим текстом для логов. Менеджеру показывают explain().
    """

    def __init__(self, message: str, *, kind: str = KIND_HTTP, status: int | None = None, detail: str = ""):
        super().__init__(message)
        self.failure = ApiFailure(kind=kind, status=status, detail=detail)

    def explain(self, action: str, not_found: str | None = None) -> str:
        return explain(action, self.failure, not_found)


def _connection_error(exc: requests.RequestException) -> GoAPIError:
    kind = KIND_TIMEOUT if isinstance(exc, requests.Timeout) else KIND_CONNECTION
    return GoAPIError(f"Ошибка соединения с Go API: {exc}", kind=kind, detail=str(exc))


@dataclass
class GoCatalogApiClient:
    timeout_seconds: int = 10

    @property
    def base_url(self) -> str:
        return settings.GO_API_BASE_URL

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if settings.GO_API_TOKEN:
            headers["Authorization"] = f"Bearer {settings.GO_API_TOKEN}"
        return headers

    def _fallback_base_url(self) -> str | None:
        """
        "api" host is resolvable only inside docker-compose network.
        For local runserver we fallback to localhost automatically.
        """
        parsed = urlparse(self.base_url)
        if parsed.hostname != "api":
            return None
        fallback = parsed._replace(netloc="localhost:8080")
        return urlunparse(fallback).rstrip("/")

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = f"{self.base_url}{path}"
        try:
            response = requests.request(
                method=method,
                url=url,
                headers=self._headers(),
                timeout=self.timeout_seconds,
                **kwargs,
            )
        except requests.RequestException as exc:
            fallback_base_url = self._fallback_base_url()
            if fallback_base_url:
                try:
                    response = requests.request(
                        method=method,
                        url=f"{fallback_base_url}{path}",
                        headers=self._headers(),
                        timeout=self.timeout_seconds,
                        **kwargs,
                    )
                except requests.RequestException:
                    raise _connection_error(exc) from exc
            else:
                raise _connection_error(exc) from exc

        if response.status_code >= 400:
            body = ""
            try:
                data = response.json()
                if isinstance(data, dict):
                    body = data.get("error") or data.get("message") or str(data)
                else:
                    body = str(data)
            except ValueError:
                body = response.text
            raise GoAPIError(
                f"Go API вернул {response.status_code}: {body}",
                status=response.status_code,
                detail=str(body),
            )

        if response.status_code == 204:
            return None
        if not response.text:
            return None
        return response.json()

    def search_items(self, query: str, limit: int = 20, offset: int = 0) -> dict[str, Any]:
        params = {"q": query, "limit": limit, "offset": offset}
        return self._request("GET", "/catalog/search", params=params)

    def list_items(self, limit: int = 20, offset: int = 0) -> dict[str, Any]:
        params = {"limit": limit, "offset": offset}
        return self._request("GET", "/catalog/list", params=params)

    def get_catalog_tree(self) -> dict[str, Any]:
        return self._request("GET", "/catalog/tree")

    def get_filter_descriptions(self) -> dict[str, Any]:
        return self._request("GET", "/catalog/filter-descriptions")

    def get_item_details(self, sku: str) -> dict[str, Any]:
        return self._request("GET", f"/catalog/items/{sku}")

    def add_item(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/admin/items", json=payload)

    def edit_item(self, item_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", f"/admin/items/edit/{item_id}", json=payload)

    def suggest_filter(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/admin/filters", json=payload)

    def get_filter_suggestions(
        self, status: str | None = None, category: str | None = None
    ) -> dict[str, Any]:
        params: dict[str, str] = {}
        if status:
            params["status"] = status
        if category:
            params["category"] = category
        return self._request("GET", "/admin/filter-suggestions", params=params)

    def review_filter_suggestion(self, suggestion_id: int, status: str) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/admin/filter-suggestions/{suggestion_id}",
            json={"status": status},
        )
