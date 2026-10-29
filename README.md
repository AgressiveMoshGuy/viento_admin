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

## Запуск в Docker (с томом для базы админки)

У админки своя SQLite-база (пользователи, сессии, журнал Django). Товары в ней не хранятся: они в Go API.
В `docker-compose.yaml` файл базы лежит в именованном томе `admin_data`, поэтому не пропадает при перезапуске
и пересборке контейнера.

```bash
cp .env.example .env          # один раз
docker compose up --build
docker compose exec admin python manage.py createsuperuser   # один раз
```

Админка откроется на `http://localhost:8001/`. Go API по умолчанию ищется на этом же компьютере
(`host.docker.internal:8080`), адрес меняется в `.env`.
`docker compose down` оставляет данные, `docker compose down -v` стирает том.
Без Docker админка работает на файле `db.sqlite3` (`make run`).

## Переменные окружения

- `ADMIN_DB_PATH` (путь к файлу SQLite; по умолчанию `db.sqlite3` в папке проекта, в Docker `/data/db.sqlite3`)
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
