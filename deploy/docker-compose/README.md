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
docker compose up -d --build

# Проверить конфиг nginx в контейнере
docker compose exec nginx nginx -t
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

## Быстрый старт

```bash
cd deploy/docker-compose
cp ../../.env.example .env
# SECRET_KEY, WEBHOOK_* и т.д.

docker compose up -d --build
curl -s http://localhost:8080/health/ready
```

## Rolling update

```bash
chmod +x rolling-update.sh
./rolling-update.sh
```
