# Jenkins + PVS-Studio Tracker (без SonarQube)

## Поток

1. TFS/Git webhook → `POST /webhook/inbound` (Basic auth `WEBHOOK_USERNAME` / `WEBHOOK_PASSWORD`)
2. Трекер запускает Jenkins job (`JENKINS_JOB_NAME`)
3. Pipeline: сборка → PVS-Studio → `pvs_snapshot.py` → `POST /api/v1/upload`
4. Опционально: `POST /api/v1/projects/{slug}/analysis-callback` с `commit` и `version`

## Переменные Jenkins (параметры job)

Трекер передаёт (совместимость со старым job сохранена):

| Параметр | Описание |
|----------|----------|
| `TRACKER_PROJECT_NAME` | Имя для upload (`project_name`) |
| `TRACKER_PROJECT_SLUG` | Slug проекта |
| `SONAR_PROJECT_NAME` / `SONAR_PROJECT_KEY` | Алиасы тех же значений |
| `COMMIT`, `FirstScan`, `LinuxBuildAgain` | Как раньше |

## Jira assignee

При создании Bug assignee берётся из **автора коммита текущего run** (`commit_author_name` / `commit_author_email` в БД), а не из `author_email` проекта. Передавайте метаданные через `commit_metadata` (файл от `pvs_snapshot.py`) или поля формы upload — иначе задачи останутся без исполнителя.

## Upload после анализа

```bash
python pvs_snapshot.py --report report.json --out-dir .

curl -s -X POST "http://tracker:8080/api/v1/upload" \
  -F "file=@report.json" \
  -F "commit_metadata=@snapshot.meta.json" \
  -F "project_name=${TRACKER_PROJECT_NAME}" \
  -F "target_platform=windows" \
  -F "branch=${ANOTHER_BRANCH}" \
  -F "commit=${COMMIT}"
```

## Callback changeset

```bash
curl -s -X POST "http://tracker:8080/api/v1/projects/${TRACKER_PROJECT_SLUG}/analysis-callback" \
  -F "commit=${COMMIT}" \
  -F "version=${BUILD_VERSION}"
```

## TFS webhook URL

Было: `http://old-host/webhook`  
Стало: `http://<tracker-host>:8080/webhook/inbound`

Заголовки без изменений: `X-TFS-Repo-Type`, `X-TFS-Repo-Name`, и т.д.

## Удалить из pipeline

- Шаги Sonar Scanner / `sonar-scanner`
- Webhook на `POST /sonarqube-webhook`

## UI в PVS-Studio Tracker

| Экран | URL | Действия |
|-------|-----|----------|
| Список проектов | `/` | Группы QA/QD/…; цвет: синий / горчичный (Jira off) / красный (анализ off) |
| Новый проект | `/ui/projects/new` | Те же поля, что в Sonar WebHook (`sonar_project_name`, `sonar_project_key`, …) |
| Дашборд → Analysis / CI | `?tab=ci` | Enable/Disable, Jira on/pause, Run analysis (admin), Clone |
| Дашборд → Settings → Parameters | `?tab=settings&settings_tab=params` | Редактирование CI-полей (`POST /ui/projects/{id}/ci`) |
| Удаление | Шапка дашборда | `POST /ui/projects/{id}/delete` (admin) |

После toggle Disable/Jira сервер возвращает фрагмент `#ci-toast-payload`; клиент показывает **toast** справа сверху (`static/app.js`, класс `sq-toast`).

Старый маршрут `/ui/projects/manage` → редирект на `/`.
