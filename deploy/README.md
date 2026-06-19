# PVS-Studio Tracker — zero-downtime deployment

Конфигурации для обновления сервиса без потери входящих веб-хуков.

На Windows **gunicorn недоступен** — каждый экземпляр запускается отдельным процессом **uvicorn**. Балансировщик распределяет трафик между 2+ экземплярами; при rolling update сначала снимается один backend с балансировки, дожидается завершение in-flight запросов, затем обновляется.

## Требования

| Требование | Почему |
|------------|--------|
| **PostgreSQL** (`DATABASE_URL`) | SQLite не поддерживает несколько процессов |
| **2+ экземпляра uvicorn** | Пока один обновляется, второй принимает веб-хуки |
| **`/health/live` и `/health/ready`** | Liveness/readiness для балансировщика |
| **`--timeout-graceful-shutdown 30`** | Дать BackgroundTasks завершить обработку веб-хука |

Критичные эндпоинты (длинные таймауты в nginx):

- `POST /webhook/inbound` — TFS/Git → Jenkins
- `POST /api/v1/upload` — загрузка отчётов из CI

## Варианты

| Вариант | Папка | Когда использовать |
|---------|-------|-------------------|
| **Nginx** | [nginx/](nginx/) | Windows Server, NSSM + nginx for Windows |
| **Compose (Windows)** | [docker-compose-windows/](docker-compose-windows/) | Windows Server + Docker Engine, контейнеры app/worker |
| **Compose (Linux)** | [docker-compose/](docker-compose/) | Linux-хост или Docker Desktop, быстрый стенд |
| **Kubernetes** | [k8s/](k8s/) | Кластер K8S, production с autoscaling |

Подробная инструкция: [docs/zero-downtime-deployment.md](../docs/zero-downtime-deployment.md).  
Очередь REST API: [docs/rest-queue.md](../docs/rest-queue.md).

## Быстрый запуск экземпляра (Windows)

```powershell
# Экземпляр 1 — порт 8081
uvicorn pvs_tracker.main:app --host 127.0.0.1 --port 8081 --timeout-graceful-shutdown 30

# Экземпляр 2 — порт 8082
uvicorn pvs_tracker.main:app --host 127.0.0.1 --port 8082 --timeout-graceful-shutdown 30
```

Nginx слушает `:8080` и проксирует на `8081`/`8082`. TFS/Git webhook URL: `http://<host>:8080/webhook/inbound`.
