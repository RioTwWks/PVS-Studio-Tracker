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

## Сборка образа: DNS, proxy и offline-режим

При `docker build` шаг `RUN Invoke-WebRequest` выполняется **внутри временного Windows-контейнера**. Ошибка:

```text
The remote name could not be resolved: 'www.python.org'
```

чаще всего означает **DNS в build-контейнере**, но в корпоративной сети часто нужны **и DNS, и proxy** — они настраиваются **отдельно** для каждого уровня.

### Где какой proxy действует

| Уровень | Наследует системный proxy? | Зачем |
|---------|---------------------------|-------|
| Браузер / пользовательские приложения | Да (Internet Options / PAC) | UI, скачивание файлов вручную |
| PowerShell на **хосте** | Частично (IE/WebRequest profile) | `Invoke-WebRequest` в интерактивной сессии |
| Служба **Docker Engine** | **Нет** | `docker pull` базовых образов |
| **`RUN` внутри `docker build`** | **Нет** | Скачивание Python/MinGit в Dockerfile |
| **Запущенные** app/worker контейнеры | **Нет** | `git clone`, Jenkins, Jira, SMTP |

Системный proxy Windows **не попадает** в build-контейнер автоматически.

### 1. Proxy для Docker Engine (pull образов)

`C:\ProgramData\docker\config\daemon.json`:

```json
{
  "dns": ["10.0.0.1"],
  "proxies": {
    "default": {
      "httpProxy": "http://proxy.corp.local:8080",
      "httpsProxy": "http://proxy.corp.local:8080",
      "noProxy": "localhost,127.0.0.1,.corp.local"
    }
  }
}
```

Перезапустите службу `docker`. Без этого `docker pull mcr.microsoft.com/...` может не работать, даже если в браузере всё открывается.

Проверка WinHTTP proxy на хосте (от имени администратора):

```powershell
netsh winhttp show proxy
```

### 2. Proxy для сборки образа (RUN в Dockerfile)

В `.env` рядом с compose:

```ini
HTTP_PROXY=http://proxy.corp.local:8080
HTTPS_PROXY=http://proxy.corp.local:8080
NO_PROXY=localhost,127.0.0.1,.corp.local
```

`docker compose build` передаст их в `Dockerfile.app` (`Invoke-WebRequest -Proxy` и `pip`).

Или явно:

```powershell
docker compose build `
  --build-arg HTTP_PROXY=http://proxy.corp.local:8080 `
  --build-arg HTTPS_PROXY=http://proxy.corp.local:8080
```

### 3. Proxy для работающих контейнеров (git, CI)

Если app/worker ходят во внешние URL через proxy, добавьте в `.env` (передаётся в контейнеры):

```ini
HTTP_PROXY=http://proxy.corp.local:8080
HTTPS_PROXY=http://proxy.corp.local:8080
NO_PROXY=localhost,127.0.0.1,.corp.local,postgres,host.docker.internal
```

Git внутри контейнера:

```powershell
git config --global http.proxy http://proxy.corp.local:8080
git config --global https.proxy http://proxy.corp.local:8080
```

(можно добавить в `Dockerfile.app` при необходимости).

### Проверка DNS и сети

```powershell
# Хост
Resolve-DnsName www.python.org
Invoke-WebRequest -Uri https://www.python.org -UseBasicParsing

# Build-контейнер (DNS)
docker run --rm mcr.microsoft.com/windows/servercore:ltsc2019-amd64 powershell -Command "Resolve-DnsName www.python.org"

# Build-контейнер (через proxy)
docker run --rm -e HTTPS_PROXY=http://proxy.corp.local:8080 mcr.microsoft.com/windows/servercore:ltsc2019-amd64 powershell -Command "Invoke-WebRequest -Uri https://www.python.org -Proxy $env:HTTPS_PROXY -UseBasicParsing"
```

### Исправление DNS для Docker Engine

Если `Resolve-DnsName` в контейнере падает — добавьте DNS в тот же `daemon.json` (см. выше `"dns": [...]`).

### Offline-сборка (без сети в build-контейнере)

1. Скачайте на **хосте** установщики в [`build-deps/`](build-deps/) — см. [`build-deps/README.md`](build-deps/README.md).
2. Соберите с флагом:

```powershell
docker compose build --build-arg USE_OFFLINE_DEPS=1
```

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
| `Dockerfile.app` | Python 3.12 + MinGit + приложение |
| `Dockerfile.postgres` | PostgreSQL 16 zip binaries |
| `rolling-update.ps1` | zero-downtime обновление |
| `.env.example` | шаблон переменных |

Подробнее: [docs/zero-downtime-deployment.md](../../docs/zero-downtime-deployment.md).
