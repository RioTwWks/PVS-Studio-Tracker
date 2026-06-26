# Zero-downtime deployment (балансировка веб-хуков)

Обновление PVS-Studio Tracker без потери входящих веб-хуков от TFS/Git и загрузок из CI.

## Проблема

На **Windows** нельзя использовать **gunicorn** (нет fork). Обычный перезапуск единственного `uvicorn` обрывает `POST /webhook/inbound` и `POST /api/v1/upload` на время деплоя.

**Решение:** несколько независимых процессов `uvicorn` за reverse proxy / ingress. При обновлении с балансировки снимается один backend, остальные продолжают принимать трафик.

```mermaid
flowchart LR
  TFS[TFS / Git / CI] --> LB[Nginx / Ingress]
  LB --> A[uvicorn :8081]
  LB --> B[uvicorn :8082]
  A --> PG[(PostgreSQL)]
  B --> PG
```

## Обязательные условия

1. **PostgreSQL** — `DATABASE_URL=postgresql+psycopg2://...`. SQLite не работает с несколькими процессами.
2. **Минимум 2 экземпляра** uvicorn на разных портах (или 2 pod / 2 контейнера).
3. **Health probes** (встроены в приложение):
   - `GET /health/live` — процесс жив (liveness)
   - `GET /health/ready` — БД доступна (readiness, HTTP 503 при ошибке)
4. **Graceful shutdown:** `--timeout-graceful-shutdown 30` — время на завершение `BackgroundTasks` после веб-хука.

Драйвер PostgreSQL для production:

```bash
pip install psycopg2-binary
```

## Вариант 1: Nginx (Windows Server)

Файлы: [`deploy/nginx/`](../deploy/nginx/)

### Архитектура

| Компонент | Роль |
|-----------|------|
| nginx for Windows | Единая точка входа `:8080`, `include upstream-active.conf` |
| `PVS-Tracker-8081` … `8084` (NSSM) | Пул uvicorn; штатно 2, spare 8083–8084 |
| `watch-instances.ps1` + Планировщик | Минимум 2 healthy; автозапуск spare |
| PostgreSQL | Общая БД |

Подробнее: [`deploy/nginx/README.md`](../deploy/nginx/README.md).

### Установка

1. Скопируйте [`deploy/nginx/nginx.conf`](../deploy/nginx/nginx.conf) и [`upstream-active.conf`](../deploy/nginx/upstream-active.conf) в каталог nginx (например `C:\nginx\conf\`).
2. Установите зависимости и `.env` с `DATABASE_URL` на PostgreSQL.
3. Настройте [`instances.config.ps1`](../deploy/nginx/instances.config.ps1) и зарегистрируйте службы:

```powershell
cd deploy\nginx
.\install-services.ps1 -AppRoot "C:\opt\pvs-tracker" -Python "C:\opt\pvs-tracker\.venv\Scripts\python.exe"
.\sync-upstream.ps1 -ReloadNginx
.\register-watchdog.ps1
```

4. Запустите nginx. Webhook URL для TFS: `http://<host>:8080/webhook/inbound`.

### Rolling update

Обновляйте экземпляры **по одному** (перед этим spare поднимается автоматически):

```powershell
# После git pull / pip install в AppRoot:
.\rolling-update.ps1 -Port 8081
.\rolling-update.ps1 -Port 8082
```

Скрипт:
1. Обеспечивает **min+1** healthy backend (запас на время drain)
2. Помечает порт `down` в upstream (`drained-ports.txt`) и делает `nginx -s reload`
3. Ждёт drain (по умолчанию 35 с)
4. Перезапускает службу NSSM
5. Ждёт `GET /health/ready`
6. Снимает drain и пересобирает upstream

Пока обновляется `8081`, трафик идёт на `8082` (+ spare `8083` при необходимости).

---

## Вариант 1b: Docker Compose (Windows containers)

Файлы: [`deploy/docker-compose-windows/`](../deploy/docker-compose-windows/)

Windows Server с **Docker Engine** (static binaries, Windows containers mode). Балансировщик — **nginx на хосте** (не в контейнере); контейнеры `app-1`/`app-2` публикуют порты `8081`/`8082`.

### Архитектура

| Компонент | Роль |
|-----------|------|
| nginx for Windows (хост) | Единая точка входа `:8080` → `127.0.0.1:8081`, `8082` |
| `app-1`, `app-2` (контейнеры) | Два uvicorn, `REST_QUEUE_MODE=external` |
| `worker-*` (контейнеры) | REST queue (Jenkins, Jira, TFS, webhook, SMTP) |
| PostgreSQL | **На хосте** (рекомендуется) или **в контейнере** (override) |

### Требования

1. Docker Engine 20.10+ (рекомендуется 29.x static zip) + **Compose CLI plugin** (`docker compose`).
2. `WINDOWS_VERSION` в `.env` совпадает с хостом (`ltsc2019-amd64` / `ltsc2022-amd64`).
3. Конфиг nginx — [`deploy/nginx/nginx.conf`](../deploy/nginx/nginx.conf) (upstream `8081`/`8082`).

### Запуск (PostgreSQL на хосте)

```powershell
cd deploy\docker-compose-windows
copy .env.example .env
# DATABASE_URL=postgresql+psycopg2://pvs:pass@host.docker.internal:5432/pvs_tracker

docker compose up -d --build
```

### Запуск (PostgreSQL в контейнере)

```powershell
docker compose -f docker-compose.yml -f docker-compose.postgres.yml up -d --build
```

### Rolling update

```powershell
.\rolling-update.ps1 -Service app-1 -NginxConf "C:\nginx\conf\nginx.conf"
.\rolling-update.ps1 -Service app-2 -NginxConf "C:\nginx\conf\nginx.conf"
```

С контейнером PostgreSQL добавьте `-WithPostgresContainer`.

Скрипт:
1. Помечает backend `down` в nginx и делает `nginx -s reload`
2. Ждёт drain (35 с)
3. `docker compose up -d --no-deps --build app-N`
4. Ждёт `GET /health/ready` на порту хоста
5. Возвращает backend в upstream

---

## Вариант 2: Docker Compose (Linux)

Файлы: [`deploy/docker-compose/`](../deploy/docker-compose/)

Подходит для Linux-хоста или **Docker Desktop на Windows** (контейнеры Linux; uvicorn внутри контейнера).

### Запуск

```bash
cd deploy/docker-compose
cp ../../.env.example .env
# Отредактируйте SECRET_KEY, WEBHOOK_* и т.д.

docker compose up -d --build
```

Публичный порт: **8080** (nginx → `app-1`, `app-2`).

### Rolling update

```bash
chmod +x rolling-update.sh
./rolling-update.sh
```

Или вручную по одному сервису:

```bash
docker compose up -d --no-deps --build app-1
# дождаться healthy
docker compose up -d --no-deps --build app-2
```

`stop_grace_period: 45s` даёт uvicorn завершить in-flight запросы перед остановкой контейнера.

---

## Вариант 3: Kubernetes

Файлы: [`deploy/k8s/`](../deploy/k8s/)

### Применение

```bash
# 1. Соберите образ
docker build -f deploy/docker-compose/Dockerfile -t pvs-tracker:0.2.0 .

# 2. Секреты (скопируйте secret.example.yaml → secret.yaml и заполните)
kubectl apply -f deploy/k8s/namespace.yaml
kubectl apply -f deploy/k8s/secret.yaml
kubectl apply -f deploy/k8s/deployment.yaml
kubectl apply -f deploy/k8s/service.yaml
kubectl apply -f deploy/k8s/ingress.yaml   # при необходимости
```

### Rolling update в K8S

```bash
kubectl set image deployment/pvs-tracker pvs-tracker=pvs-tracker:0.2.1 -n pvs-tracker
kubectl rollout status deployment/pvs-tracker -n pvs-tracker
```

В [`deployment.yaml`](../deploy/k8s/deployment.yaml):

| Параметр | Значение | Назначение |
|----------|----------|------------|
| `replicas: 2` | 2 pod | Резерв при обновлении |
| `maxUnavailable: 0` | — | Старый pod не снимается, пока новый не ready |
| `maxSurge: 1` | — | Временно 3 pod на время rollout |
| `readinessProbe` | `/health/ready` | Трафик только на готовые pod |
| `preStop: sleep 15` | — | Endpoints успевают обновиться до SIGTERM |
| `terminationGracePeriodSeconds: 60` | — | Время на graceful uvicorn shutdown |

Ingress-аннотации задают таймауты 300 с для длинных веб-хуков/upload.

---

## Проверка

```bash
curl -s http://localhost:8080/health/live
curl -s http://localhost:8080/health/ready
curl -s http://localhost:8080/webhook/inbound/health
```

Во время rolling update повторите `POST /webhook/inbound` — запросы не должны получать connection refused.

## Сравнение вариантов

| | Nginx + NSSM | Compose (Windows) | Compose (Linux) | Kubernetes |
|---|--------------|-------------------|-----------------|------------|
| ОС хоста | Windows Server | Windows Server + Docker | Linux / Docker Desktop | Кластер |
| Процесс приложения | uvicorn (Windows) | uvicorn (Win container) | uvicorn (Linux container) | uvicorn (pod) |
| Балансировщик | nginx for Windows | nginx на хосте | nginx container | Service + Ingress |
| Rolling update | `rolling-update.ps1` | `docker-compose-windows/rolling-update.ps1` | `rolling-update.sh` | `kubectl rollout` |
| БД | Внешний PostgreSQL | хост / контейнер | postgres service | Внешний / operator |

## См. также

- [jenkins-ci.md](jenkins-ci.md) — настройка `POST /webhook/inbound`
- [quick-reference.md](quick-reference.md) — API и переменные окружения
- [`deploy/README.md`](../deploy/README.md) — краткий указатель по конфигам
