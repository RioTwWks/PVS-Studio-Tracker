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

## Установка Docker Engine 29.x (с MCR / Docker 19.03)

Скрипт: [`install-docker-engine.ps1`](install-docker-engine.ps1) — скачивает static zip, заменяет бинарники, регистрирует службу, ставит Compose plugin.

**PowerShell от администратора:**

```powershell
cd deploy\docker-compose-windows

# Базовая установка (online)
.\install-docker-engine.ps1

# С DNS и proxy для daemon (работает на 29.x; на 19.03 блок proxies ломает службу)
.\install-docker-engine.ps1 -DockerVersion 29.5.3 `
  -DnsServers 10.0.0.1 `
  -DaemonHttpProxy http://proxy.corp.local:8080 `
  -DaemonHttpsProxy http://proxy.corp.local:8080 `
  -DaemonNoProxy "localhost,127.0.0.1,.corp.local"

# Скачивание zip через proxy (на хосте)
.\install-docker-engine.ps1 -HttpProxy http://proxy.corp.local:8080 -HttpsProxy http://proxy.corp.local:8080

# Offline — zip уже на диске
.\install-docker-engine.ps1 -ZipPath C:\Install\docker-29.5.3.zip
```

Проверка:

```powershell
docker version
docker compose version
docker run --rm mcr.microsoft.com/windows/nanoserver:ltsc2019 cmd /c echo OK
```

Пример `daemon.json` для ручной правки: [`daemon.json.example`](daemon.json.example).

### Если служба не стартует после правки daemon.json

```powershell
Rename-Item C:\ProgramData\docker\config\daemon.json daemon.json.bak -ErrorAction SilentlyContinue
Restart-Service docker
Get-EventLog -LogName Application -Source docker -Newest 5 | Format-List Message
```

Ошибка `directives don't match any configuration option: default` — это **Docker 19.03**; блок `"proxies": { "default": ... }` поддерживается в **20.10+ / 29.x**.

### Ручная установка (без скрипта)

1. Скачать: https://download.docker.com/win/static/stable/x86_64/docker-29.5.3.zip  
2. Остановить службу, `dockerd --unregister-service`  
3. Распаковать в `C:\Program Files\Docker`, добавить в PATH  
4. `dockerd --register-service` → `Start-Service docker`  
5. Compose plugin: `docker-compose-windows-x86_64.exe` → `C:\Program Files\Docker\cli-plugins\docker-compose.exe`  
   (релизы: https://github.com/docker/compose/releases)

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

## Troubleshooting

### `initdb failed with exit code -1073741515`

Код `0xC000013D` — не хватает **Visual C++ Redistributable** для PostgreSQL zip binaries. Образ postgres теперь ставит `vc_redist.x64.exe` при сборке. Пересоберите:

```powershell
docker compose -f docker-compose.yml -f docker-compose.postgres.yml build postgres --no-cache
```

Offline: положите `vc_redist.x64.exe` в `build-deps/` (см. [`build-deps/README.md`](build-deps/README.md)).

### `app-1` / `app-2` рестартуются, `curl :8081` timeout

1. Логи приложения (главный источник):

```powershell
docker logs docker-compose-windows-app-1-1 --tail 100
```

2. Проверка изнутри контейнера (если успеет подняться):

```powershell
docker exec docker-compose-windows-app-1-1 powershell -Command "Invoke-WebRequest http://127.0.0.1:8080/health/live -UseBasicParsing"
```

Если **внутри OK, с хоста timeout** — Windows Firewall / HNS для портов `8081`/`8082`.

3. Частая причина: в `.env` пустые `GIT_CACHE_DIR=` / `SNAPSHOTS_DIR=` ломали импорт `main.py` (воркеры при этом живут). Обновите `.env` или `git pull` — в compose заданы пути `C:/app/data/...`.

4. Проверьте `DATABASE_URL` в контейнере (должен быть `@postgres:5432`, не `host.docker.internal`):

```powershell
docker inspect docker-compose-windows-app-1-1 --format "{{range .Config.Env}}{{println .}}{{end}}" | findstr DATABASE
```

5. **`connection to server at "postgres" ... Connection timed out`** — на Windows containers прямой TCP между контейнерами часто не работает. **Решение по умолчанию:** `POSTGRES_HOST=host.docker.internal` в `.env` и опубликованный порт `5432:5432` (см. `docker-compose.postgres.yml`).

```powershell
# В .env:
POSTGRES_HOST=host.docker.internal
POSTGRES_PASSWORD=pvs

docker compose -f docker-compose.yml -f docker-compose.postgres.yml up -d --force-recreate
docker inspect docker-compose-windows-app-1-1 --format "{{range .Config.Env}}{{println .}}{{end}}" | findstr DATABASE
```

Проверка с хоста (published port):

```powershell
Test-NetConnection localhost -Port 5432
```

Проверка из app (должен быть host.docker.internal, не postgres):

```powershell
docker exec docker-compose-windows-app-1-1 powershell -Command "python -c \"import os; print(os.environ.get('DATABASE_URL',''))\""
```

### `initdb: Permission denied` на `C:/pgsql/data`

На Windows **named volume** не даёт `initdb` менять ACL каталога. Решение в compose: **bind mount** `./pgdata` (уже в `docker-compose.postgres.yml`). Entrypoint инициализирует кластер во временной папке образа и копирует в `pgdata`.

Сброс БД на dev-стенде:

```powershell
docker compose -f docker-compose.yml -f docker-compose.postgres.yml down
Remove-Item -Recurse -Force .\pgdata\*
docker compose -f docker-compose.yml -f docker-compose.postgres.yml up -d
```

### Volume `pvs_pg_data` не удаляется / network in use

Старый named volume можно удалить вручную при остановленной службе Docker:

```powershell
docker compose -f docker-compose.yml -f docker-compose.postgres.yml down --remove-orphans
Stop-Service docker
Remove-Item -Recurse -Force C:\Docker\volumes\docker-compose-windows_pvs_pg_data -ErrorAction SilentlyContinue
Start-Service docker
```

Текущий стек использует `./pgdata` вместо named volume — старый `pvs_pg_data` можно просто игнорировать.

### Orphan containers после обновления compose

```powershell
docker compose -f docker-compose.yml -f docker-compose.postgres.yml up -d --remove-orphans
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
