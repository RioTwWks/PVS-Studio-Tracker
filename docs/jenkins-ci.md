# Jenkins + PVS-Studio Tracker (без SonarQube)

[← Документация](README.md)

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

## Метаданные коммита (`.meta.json`)

Скрипт `pvs_snapshot.py` в корне репозитория при сборке снапшота (если в `base_dir` есть `.git`) записывает JSON рядом со снапшотом:

| Поле | Описание |
|------|----------|
| `commit` | Хеш коммита (полный или короткий) |
| `commit_author_name` | Имя автора из `git log` |
| `commit_author_email` | Email автора |
| `release_version` | Версия продукта (`major.minor.patch`), как `sonar.projectVersion` |
| `report_type` | `incremental` (по умолчанию) или `full` — scope diff при upload (см. ниже) |

Версия определяется в `pvs_snapshot.py` по тем же правилам, что Jenkins-скрипты `get_version_fastapi.py` / `get-version-linux.py` (Version.rc, Version.cmake, CMakeLists.txt, VersionInfo.h для QA).

Пример файла `report.meta.json`:

```json
{
  "commit": "a1b2c3d4e5f6789012345678901234567890abcd",
  "commit_author_name": "Ivan Petrov",
  "commit_author_email": "ivan@company.ru",
  "release_version": "8.10.3",
  "report_type": "incremental"
}
```

### Тип отчёта (`report_type`)

Типичный CI-пайплайн PVS выполняет **инкрементальный** анализ (только изменённые файлы). В этом случае передавайте `report_type=incremental` (значение по умолчанию) — трекер **не** будет помечать отсутствующие в JSON warning'и как `fixed`.

Для **полного** снимка кодовой базы (например, ночной full scan) укажите `report_type=full` — исчезнувшие с прошлого run fingerprint'ы получат `status=fixed`.

```bash
# Инкрементальный анализ (CI по умолчанию)
-F "report_type=incremental"

# Полный снимок
-F "report_type=full"
```

Имя по умолчанию: для `snapshot.json.gz` → `snapshot.meta.json` (см. `default_metadata_path` в `pvs_snapshot.py`).

### Загрузка в трекер

Поле multipart: **`commit_metadata`** (не имя файла на диске — любой `.json`).

Приоритет при слиянии (`upload_metadata.merge_commit_upload_fields`):

1. Непустые поля формы (`commit`, `commit_author_name`, `commit_author_email`, `release_version`, `report_type`)
2. Значения из JSON-файла

Куда попадает в БД:

- `Run.commit`, `Run.commit_author_name`, `Run.commit_author_email`, `Run.release_version`, `Run.report_type`
- `Project.release_version` обновляется при upload (как раньше через `analysis-callback`)
- на графике дашборда по оси X и в tooltip отображается `release_version` каждого анализа
- **new** issues → `Issue.author_*` от коммита run (`issue_author.py`)
- Jira Bug → assignee из автора коммита run / issue

Без metadata Jira-задачи могут остаться без исполнителя, даже если в проекте указан `author_email`.

### Генерация metadata в pipeline

```bash
# Снапшот + metadata (Git + версия из исходников)
python pvs_snapshot.py report.json snapshot.json.gz "${WORKSPACE}" \
  --group "${GROUP}" \
  --build-system cmake \
  --project-key "${SONAR_PROJECT_KEY}" \
  --project-name "${SONAR_PROJECT_NAME}" \
  --sln-name "${sln_name}" \
  --select-vcxproj "${SELECT_VCXPROJ}" \
  --exclude-path "${PVS_EXCLUDE_PATH}"

# Явный путь metadata
python pvs_snapshot.py report.json snapshot.json.gz "${WORKSPACE}" --metadata-out snapshot.meta.json
```

Флаги: `--skip-author` / `--skip-version` / `--no-metadata`; `--release-version` — задать версию вручную; `--commit` — явный ref для `git log`.

## Jira assignee

При создании Bug assignee берётся из **автора коммита текущего run** (`commit_author_name` / `commit_author_email`), а не из `author_email` проекта. Обязательно передавайте `commit_metadata` или поля формы upload.

## Upload после анализа

```bash
python pvs_snapshot.py report.json snapshot.json.gz "${WORKSPACE}"

curl -s -X POST "http://tracker:8080/api/v1/upload" \
  -F "file=@report.json" \
  -F "commit_metadata=@snapshot.meta.json" \
  -F "project_name=${TRACKER_PROJECT_NAME}" \
  -F "target_platform=windows" \
  -F "report_type=incremental" \
  -F "branch=${ANOTHER_BRANCH}"
```

Поля формы вместо файла (опционально):

```bash
  -F "commit=${COMMIT}" \
  -F "commit_author_name=${GIT_AUTHOR_NAME}" \
  -F "commit_author_email=${GIT_AUTHOR_EMAIL}"
```

UI: дашборд → **Upload** → поле «Метаданные коммита (.json)».

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

Проверка: `GET /webhook/inbound/health`

## Удалить из pipeline

- Шаги Sonar Scanner / `sonar-scanner`
- Webhook на `POST /sonarqube-webhook`

## UI в PVS-Studio Tracker

| Экран | URL | Действия |
|-------|-----|----------|
| Список проектов | `/` | Группы из `ProjectGroup` (или fallback QA/QD/…); цвет карточки |
| Новый / редактирование | `/ui/projects/new`, `/ui/projects/{id}/edit` | Sonar-поля, группа |
| Дашборд → Analysis / CI | `?tab=ci` | Enable/Disable, Jira, Run analysis, Clone |
| Дашборд → Settings → Parameters | `?tab=settings&settings_tab=params` | `POST /ui/projects/{id}/ci` |
| Upload | `?tab=upload` | JSON + `commit_metadata` + выбор `report_type` |
| Удаление | Шапка дашборда | `POST /ui/projects/{id}/delete` (admin) |

После toggle Disable/Jira сервер возвращает `#ci-toast-payload`; toast — `static/app.js` (`sq-toast`).

`/ui/projects/manage` → редирект на `/`.

## См. также

- [quick-reference.md](quick-reference.md) — curl для API
- [README.md](../README.md) — переменные `JENKINS_*`, `JIRA_*` в `.env.example`
