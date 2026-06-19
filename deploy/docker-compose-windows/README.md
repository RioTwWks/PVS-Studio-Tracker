# Docker Compose — Windows containers

Zero-downtime стек для **Windows Server** с Docker Engine (native Windows containers).

| Компонент | Где |
|-----------|-----|
| **nginx** | На **хосте** — [`deploy/nginx/nginx.conf`](../nginx/nginx.conf), порт `:8080` |
| **app-1, app-2** | Windows-контейнеры, порты хоста `8081`, `8082` |
| **worker-*** | Отдельные Windows-контейнеры (`REST_QUEUE_MODE=external`) |
| **PostgreSQL** | На хосте **или** в контейнере (на выбор) |

## Требования

1. Windows Server 2019/2022 с **Docker Engine** (static zip, например 29.x) в режиме **Windows containers**.
2. **Compose CLI plugin** установлен отдельно (`docker compose version`).
3. Версия LTSC образа (`WINDOWS_VERSION`) совпадает с хостом (`ltsc2019-amd64` / `ltsc2022-amd64`).
4. **nginx for Windows** на хосте — единая точка входа `:8080` (см. [`deploy/nginx/`](../nginx/)).
5. **PostgreSQL** — не SQLite.

## Быстрый старт

### 1. nginx на хосте

```powershell
# Скопируйте deploy\nginx\nginx.conf → C:\nginx\conf\nginx.conf
# Upstream уже настроен на 127.0.0.1:8081 и 127.0.0.1:8082
nginx
```

### 2. Переменные окружения

```powershell
cd deploy\docker-compose-windows
copy .env.example .env
# Отредактируйте SECRET_KEY, DATABASE_URL, WEBHOOK_* и т.д.
```

### 3a. PostgreSQL на хосте (рекомендуется)

Установите PostgreSQL на Windows Server. В `.env`:

```ini
DATABASE_URL=postgresql+psycopg2://pvs:password@host.docker.internal:5432/pvs_tracker
```

Разрешите подключения с Docker-сети в `pg_hba.conf` и `listen_addresses = '*'` (или конкретный subnet NAT).

```powershell
docker compose up -d --build
```

### 3b. PostgreSQL в контейнере (опционально)

```powershell
docker compose -f docker-compose.yml -f docker-compose.postgres.yml up -d --build
```

`DATABASE_URL` для app/worker подставляется из `docker-compose.postgres.yml`.

> Контейнер PostgreSQL на Windows — для dev/стенда. Для production предпочтителен инстанс на хосте или отдельный сервер БД.

## Проверка

```powershell
curl http://localhost:8081/health/ready
curl http://localhost:8082/health/ready
curl http://localhost:8080/health/ready
```

Webhook URL для TFS: `http://<host>:8080/webhook/inbound`.

## Rolling update

Обновляйте **по одному** контейнеру (nginx drain → rebuild → readiness → return to upstream):

```powershell
.\rolling-update.ps1 -Service app-1 -NginxConf "C:\nginx\conf\nginx.conf"
.\rolling-update.ps1 -Service app-2 -NginxConf "C:\nginx\conf\nginx.conf"
```

С PostgreSQL в контейнере:

```powershell
.\rolling-update.ps1 -Service app-1 -NginxConf "C:\nginx\conf\nginx.conf" -WithPostgresContainer
```

## Файлы

| Файл | Назначение |
|------|------------|
| `docker-compose.yml` | app-1, app-2, workers (БД на хосте) |
| `docker-compose.postgres.yml` | override: контейнер `postgres` |
| `Dockerfile.app` | Python 3.12 + приложение |
| `Dockerfile.postgres` | PostgreSQL 16 zip binaries |
| `rolling-update.ps1` | zero-downtime обновление |
| `.env.example` | шаблон переменных |

Подробнее: [docs/zero-downtime-deployment.md](../../docs/zero-downtime-deployment.md).
