# Docker Compose — Linux

Стек: **postgres** + **app-1** / **app-2** (uvicorn) + **worker-*** + **nginx** (в контейнере).

Публичный URL: `http://localhost:8080`

## Dockerfile и `CMD`

`CMD` в [`Dockerfile`](Dockerfile) — обычная директива Docker для **Linux-контейнеров**: команда по умолчанию при старте контейнера. Это не «windows-специфика».

| Платформа | Как запускается uvicorn |
|-----------|-------------------------|
| Linux compose | `CMD ["uvicorn", ...]` в Dockerfile |
| Windows compose | `ENTRYPOINT app-entrypoint.ps1` + `command` в compose |

На Linux фоновая инициализация БД в lifespan работает штатно; отдельный `startup_init` в entrypoint не нужен.

Переопределить команду можно в `docker-compose.yml` (`command:`), как у воркеров.

## nginx.conf — только для контейнера `nginx`

Файл [`nginx.conf`](nginx.conf) рассчитан на сервис **`nginx` внутри `docker compose`**. Имена `app-1` и `app-2` — DNS Docker-сети compose; **на хосте Linux они не резолвятся**.

```bash
# Правильно: поднять весь стек
cd deploy/docker-compose
./compose.sh up -d --build

# Проверить конфиг nginx в контейнере
./compose.sh exec nginx nginx -t
```

```bash
# Неправильно для этого файла:
sudo cp nginx.conf /etc/nginx/nginx.conf
sudo nginx -t   # host not found in upstream "app-1:8080"
```

### nginx на хосте (без контейнера nginx)

Используйте [`deploy/nginx/nginx.conf`](../nginx/nginx.conf) с `127.0.0.1:8081` / `8082` и опубликуйте порты app в compose:

```yaml
app-1:
  ports:
    - "127.0.0.1:8081:8080"
app-2:
  ports:
    - "127.0.0.1:8082:8080"
```

Либо оставьте nginx в compose (рекомендуется) — отдельный nginx на хосте не нужен.

## Требования: Docker + Compose

Нужны **Docker Engine** и **Compose** (один из вариантов):

| Команда | Что это |
|---------|---------|
| `docker compose` | Compose **v2** (плагин к Docker CLI) — рекомендуется |
| `docker-compose` | Compose **v1** (отдельный бинарник) — тоже подходит |

Проверка:

```bash
docker --version
docker compose version    # v2
# или
docker-compose --version  # v1
```

Если `docker compose up -d` выдаёт `unknown shorthand flag: 'd' in -d` — плагин Compose **не установлен**. Docker не понимает подкоманду `compose`, флаги попадают не туда.

**Установка (Ubuntu/Debian):**

```bash
sudo apt-get update
sudo apt-get install -y docker.io docker-compose-plugin
sudo usermod -aG docker "$USER"   # перелогиниться после этого
docker compose version
```

Альтернатива v1:

```bash
sudo apt-get install -y docker-compose
docker-compose --version
```

**Запуск через wrapper** (сам подберёт v2 или v1):

```bash
cd deploy/docker-compose
chmod +x compose.sh
./compose.sh up -d --build
```

## Корпоративный proxy

Ошибка `Get "https://registry-1.docker.io/v2/": ... Client.Timeout` при `docker compose up` — **Docker daemon не ходит в интернет** (или Docker Hub недоступен). Переменные `HTTP_PROXY` в `.env` **не влияют** на `docker pull` базовых образов (`postgres`, `nginx`, `python`).

### Где какой proxy

| Уровень | Файл / место | Для чего |
|---------|--------------|----------|
| **Docker daemon** | `/etc/docker/daemon.json` | `docker pull`, скачивание `postgres:16-alpine`, `nginx:1.27-alpine`, `python:3.12-slim` |
| **compose build** | `.env` → `HTTP_PROXY` / `HTTPS_PROXY` | `apt-get`, `pip install` внутри Dockerfile |
| **running app** | `.env` → те же переменные | исходящие HTTP из контейнеров (Jenkins, Jira, …) |

### 1. Proxy для Docker daemon (обязательно для pull)

Скопируйте [`daemon.json.example`](daemon.json.example), подставьте адрес proxy:

```bash
sudo cp deploy/docker-compose/daemon.json.example /etc/docker/daemon.json
# отредактируйте httpProxy / httpsProxy / noProxy

sudo systemctl daemon-reload
sudo systemctl restart docker

# проверка
docker pull hello-world
docker pull postgres:16-alpine
```

Альтернатива (systemd, если `daemon.json` не подхватывает proxies):

```bash
sudo mkdir -p /etc/systemd/system/docker.service.d
sudo tee /etc/systemd/system/docker.service.d/http-proxy.conf <<'EOF'
[Service]
Environment="HTTP_PROXY=http://proxy.corp.local:8080"
Environment="HTTPS_PROXY=http://proxy.corp.local:8080"
Environment="NO_PROXY=localhost,127.0.0.1,.corp.local"
EOF
sudo systemctl daemon-reload
sudo systemctl restart docker
```

### 2. Proxy для сборки app (pip / apt)

```bash
cd deploy/docker-compose
cp .env.example .env
```

Раскомментируйте в `.env`:

```ini
HTTP_PROXY=http://proxy.corp.local:8080
HTTPS_PROXY=http://proxy.corp.local:8080
NO_PROXY=localhost,127.0.0.1,.corp.local,postgres
```

```bash
./compose.sh build --no-cache app-1
```

### 3. Проверка всего стека

```bash
./compose.sh up -d --build
./compose.sh ps
curl -s http://localhost:8080/health/ready
```

## Быстрый старт

```bash
cd deploy/docker-compose
cp .env.example .env
# SECRET_KEY, WEBHOOK_*; при proxy — см. раздел выше

./compose.sh up -d --build
# или: docker compose up -d --build
# или: docker-compose up -d --build

curl -s http://localhost:8080/health/ready
```

## Rolling update

```bash
chmod +x rolling-update.sh
./rolling-update.sh
```
