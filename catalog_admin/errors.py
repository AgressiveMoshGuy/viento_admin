"""Понятные сообщения об ошибках для менеджера.

Модуль не зависит от Django и requests, поэтому его можно проверять отдельно.
Сырой текст от сервера в интерфейс не попадает: он уходит в лог, а менеджер видит
короткое объяснение и, если сервер ответил, код ошибки, который можно назвать
администратору.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

KIND_CONNECTION = "connection"  # сервер недоступен
KIND_TIMEOUT = "timeout"  # сервер не ответил вовремя
KIND_HTTP = "http"  # сервер ответил кодом 400 и выше

# Подсказки по тексту ответа проверяются по порядку, регистр не важен. Тексты Go и
# PostgreSQL могут измениться, поэтому это только уточнение: если ничего не подошло,
# работает ответ по коду состояния.
_DETAIL_HINTS = (
    ("duplicate key", "Товар с таким артикулом (SKU) уже есть."),
    ("unique constraint", "Товар с таким артикулом (SKU) уже есть."),
    ("foreign key", "Такой категории нет. Проверьте ID категории."),
    ("cannot unmarshal", "В одном из полей значение не того типа, например текст вместо числа."),
    ("invalid input syntax for type json", "Свойства записаны неверно. Нужен объект в фигурных скобках."),
    ("invalid character", "Свойства записаны неверно. Проверьте кавычки, запятые и скобки."),
    ("unexpected end of json", "Данные пришли не полностью. Отправьте форму ещё раз."),
)

_BY_STATUS = {
    400: "Сервер не принял данные. Проверьте, что поля заполнены правильно.",
    401: "Сервер каталога не пустил админку. Сообщите администратору: нужно проверить ключ доступа.",
    403: "У админки нет прав на это действие. Сообщите администратору.",
    404: "Такой записи на сервере нет. Возможно, её уже удалили.",
    409: "Такая запись уже существует.",
    413: "Данных слишком много. Сократите описание или свойства.",
    422: "Данные не прошли проверку. Проверьте значения полей.",
    429: "Слишком много запросов. Подождите минуту и повторите.",
}
_SERVER_ERROR = "На сервере каталога произошла ошибка. Попробуйте позже. Если повторится, сообщите администратору."
_UNKNOWN = "Сервер ответил неожиданно. Попробуйте ещё раз."
_CONNECTION = "Не удаётся связаться с сервером каталога. Проверьте, что он запущен, и повторите."
_TIMEOUT = "Сервер каталога долго не отвечает. Попробуйте ещё раз через минуту."


@dataclass(frozen=True)
class ApiFailure:
    kind: str
    status: int | None = None
    detail: str = ""  # сырой текст от сервера или от requests, только для логов


def reason(failure: ApiFailure, not_found: str | None = None) -> str:
    """Причина ошибки простыми словами."""
    if failure.kind == KIND_CONNECTION:
        return _CONNECTION
    if failure.kind == KIND_TIMEOUT:
        return _TIMEOUT

    status = failure.status
    if status == 404 and not_found:
        return not_found

    detail = (failure.detail or "").lower()
    for needle, text in _DETAIL_HINTS:
        if needle in detail:
            return text

    if status in _BY_STATUS:
        return _BY_STATUS[status]
    if status is not None and status >= 500:
        return _SERVER_ERROR
    return _UNKNOWN


def explain(action: str, failure: ApiFailure, not_found: str | None = None) -> str:
    """Полное сообщение: что не удалось и почему.

    action: глагол в неопределённой форме, например "сохранить товар".
    not_found: свой текст для ответа 404, если известно, что именно не нашлось.
    """
    text = f"Не удалось {action}. {reason(failure, not_found)}"
    if failure.kind == KIND_HTTP and failure.status:
        text += f" (код ошибки {failure.status})"
    return text


def describe_json_error(exc: json.JSONDecodeError) -> str:
    """Где в тексте ошибка JSON, по-русски."""
    return f"Ошибка в строке {exc.lineno}, символ {exc.colno}. Проверьте кавычки, запятые и скобки."
