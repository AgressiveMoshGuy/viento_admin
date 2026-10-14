# Django Admin API Backoffice (MVP)

Минимальная отдельная админка на Django, которая работает с каталогом через Go API.

## Что есть в MVP

- Поиск товаров через `GET /api/catalog/search`
- Просмотр карточки товара через `GET /api/catalog/items/{sku}`
- Создание товара через `POST /api/admin/items`
- Редактирование товара через `POST /api/admin/items/edit/{item_id}`
- Создание предложения нового фильтра через `POST /api/admin/filters`
- Модерация предложений фильтров через:
  - `GET /api/admin/filter-suggestions`
  - `POST /api/admin/filter-suggestions/{suggestion_id}`

## Быстрый старт

```bash
cd django_admin_api
make run
```

Откройте: `http://localhost:8001/`

## Переменные окружения

- `GO_API_BASE_URL` (по умолчанию `http://localhost:8080/api`)
- `GO_API_TOKEN` (Bearer token для админских эндпоинтов)
- `DJANGO_SECRET_KEY`
- `DJANGO_DEBUG`
- `DJANGO_ALLOWED_HOSTS` (по умолчанию `localhost,127.0.0.1`)
- `DJANGO_CSRF_TRUSTED_ORIGINS` (по умолчанию `http://localhost:8001,http://127.0.0.1:8001`)

Пример:

```bash
GO_API_BASE_URL=http://localhost:8080/api GO_API_TOKEN=your_token make run
```

## Первый вход

Создайте админа:

```bash
cd django_admin_api
make superuser
```
