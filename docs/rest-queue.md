# REST API job queue

Очередь исходящих вызовов к внешним сервисам. **Один воркер на service** — последовательная обработка REST-запросов без гонок и rate-limit сюрпризов.

## Сервисы

| Service | Задачи | Примеры |
|---------|--------|---------|
| `jenkins` | `trigger_build` | TFS webhook → Jenkins, ручной Run analysis |
| `jira` | `sync_run` | Создание/комментарии Jira после upload |
| `tfs` | `latest_changeset`, `check_tfvc_*` | TFVC REST API |
| `webhook` | `upload`, `quality_gate` | Исходящие `WEBHOOK_URL` |
| `smtp` | `api_upload_notify` | Email подписчикам API upload |

Таблица БД: `restqueuejob` (создаётся через `SQLModel.metadata.create_all`).

Для нескольких процессов (Docker/K8S) нужен **PostgreSQL** (`FOR UPDATE SKIP LOCKED`).

## Режимы запуска

### 1. Embedded (uvicorn, Windows по умолчанию)

```env
REST_QUEUE_MODE=embedded
REST_QUEUE_POLL_INTERVAL=1.0
```

При старте `uvicorn pvs_tracker.main:app` в lifespan поднимаются **5 daemon-потоков** (по одному на service). Отдельные процессы не нужны.

```powershell
uvicorn pvs_tracker.main:app --host 0.0.0.0 --port 8080
```

### 2. External (Docker Compose / K8S)

API-контейнеры только ставят задачи в очередь:

```env
REST_QUEUE_MODE=external
```

Воркеры — отдельные контейнеры/pod:

```bash
python -m pvs_tracker.rest_queue --service jenkins
python -m pvs_tracker.rest_queue --service all   # все 5 в одном процессе (dev)
```

**Docker Compose:** сервисы `worker-jenkins`, `worker-jira`, `worker-tfs`, `worker-webhook`, `worker-smtp` в [`deploy/docker-compose/docker-compose.yml`](../deploy/docker-compose/docker-compose.yml).

**Kubernetes:** [`deploy/k8s/workers.yaml`](../deploy/k8s/workers.yaml) — по Deployment на service.

```bash
kubectl apply -f deploy/k8s/workers.yaml
```

## Повторы и ошибки

- До **5 попыток** с экспоненциальной задержкой (15s × attempt)
- Статусы: `pending` → `processing` → `done` | `failed`
- Логи: `REST queue enqueued`, `REST queue failed`

## Использование из кода

```python
from pvs_tracker.rest_queue.client import enqueue_jenkins_trigger, enqueue_jira_sync

enqueue_jenkins_trigger(project_id, commit_id, "NO", linux=True, modified_files=[])
enqueue_jira_sync(project_id, run_id)
```

## См. также

- [zero-downtime-deployment.md](zero-downtime-deployment.md) — балансировка uvicorn
- [jenkins-ci.md](jenkins-ci.md) — inbound webhook
