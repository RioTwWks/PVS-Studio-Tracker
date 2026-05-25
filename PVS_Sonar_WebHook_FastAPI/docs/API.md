# Документация API

REST API проекта SAST PVS+Sonar Project Manager.

Базовый URL: `http://localhost:8080`

## Аутентификация

### Аутентификация веб-хуков
Эндпоинты веб-хуков требуют HTTP Basic Authentication.

```bash
curl -u username:password http://localhost:8080/webhook
```

### Административная аутентификация
Административные эндпоинты проверяют IP-адрес и имя хоста по настроенным спискам.

---

## Страницы (UI)

### Получить форму проекта
```http
GET /
```

Отображает форму создания/редактирования проекта.

**Параметры запроса:**
- `clone_id` (опционально) — ID проекта для клонирования
- `edit_id` (опционально) — ID проекта для редактирования

**Ответ:** HTML страница

---

### Получить список проектов
```http
GET /list
```

Отображает список всех проектов с действиями управления.

**Ответ:** HTML страница

---

## Projects API

### Создать/Обновить проект
```http
POST /project
Content-Type: application/x-www-form-urlencoded
```

Создаёт новый проект или обновляет существующий.

**Поля формы:**

| Поле | Тип | Обязательно | Описание |
|------|-----|-------------|----------|
| `group_id` | string | Да | ID группы проекта |
| `author_email` | string | Да | Email автора |
| `sonar_project_name` | string | Да | Имя проекта в SonarQube |
| `sonar_project_key` | string | Да | Ключ проекта в SonarQube |
| `jira_project` | string | Нет | Ключ проекта в Jira |
| `cvs_system` | string | Да | Система контроля версий (Git/TFVC) |
| `tfs_path` | string | Да | Путь к репозиторию TFS |
| `sub_modules` | boolean | Нет | Включить sub-модули |
| `another_branch` | string | Да | Ветка |
| `life_time` | string | Нет | Время жизни проекта |
| `cmake_msbuild` | string | Нет | Система сборки (CMake/MSBuild) |
| `select_vcxproj` | string | Нет | Выбранные vcxproj файлы |
| `pvs_exclude_vcxproj` | string | Нет | Исключённые vcxproj файлы |
| `pvs_exclude_path` | string | Нет | Исключённые директории |
| `pvs_check_conf_name` | string | Да | Конфигурация PVS |
| `pvs_check_arch` | string | Да | Архитектура PVS |
| `cmake_win_commands` | string | Нет | Команды CMake для Windows |
| `cmake_linux_commands` | string | Нет | Команды CMake для Linux |
| `disabled` | boolean | Нет | Отключить проект |
| `last_processed_changeset` | string | Нет | Последний обработанный changeset |
| `version` | string | Нет | Версия проекта |
| `disable_jira` | boolean | Нет | Отключить создание задач в Jira |
| `edit_id` | string | Нет | ID проекта для обновления |

**Ответ:** 303 Redirect на `/list`

---

### Клонировать проект
```http
POST /project/clone/{project_id}
```

Клонирует существующий проект.

**Параметры пути:**
- `project_id` (integer) — ID проекта для клонирования

**Ответ:** 303 Redirect на `/list`

---

### Отключить проект
```http
POST /project/disable/{project_id}
```

Отключает анализ проекта.

**Параметры пути:**
- `project_id` (integer) — ID проекта

**Ответ:** 303 Redirect на `/list`

---

### Включить проект
```http
POST /project/enable/{project_id}
```

Включает анализ проекта.

**Параметры пути:**
- `project_id` (integer) — ID проекта

**Ответ:** 303 Redirect на `/list`

---

### Удалить проект (только администратор)
```http
POST /project/delete/{project_id}
```

Удаляет проект из базы данных и SonarQube.

**Права:** Требуется IP/hostname администратора

**Параметры пути:**
- `project_id` (integer) — ID проекта

**Ответ:** 303 Redirect на `/list`

---

### Запустить анализ
```http
POST /project/analyze/{project_id}
```

Запускает немедленный анализ для проекта.

**Параметры пути:**
- `project_id` (integer) — ID проекта

**Ответ:** 303 Redirect на `/list`

---

### Отключить задачи Jira
```http
POST /project/disable_jira/{project_id}
```

Отключает создание задач Jira для проекта.

**Параметры пути:**
- `project_id` (integer) — ID проекта

**Ответ:** 303 Redirect на `/list`

---

### Включить задачи Jira
```http
POST /project/enable_jira/{project_id}
```

Включает создание задач Jira для проекта.

**Параметры пути:**
- `project_id` (integer) — ID проекта

**Ответ:** 303 Redirect на `/list`

---

## Веб-хуки

### TFS/Git веб-хук
```http
POST /webhook
Authorization: Basic <credentials>
```

Получает веб-хук от TFS/Azure DevOps.

**Заголовки:**
- `X-TFS-Repo-Type` — Тип репозитория
- `X-TFS-Repo-Name` — Название репозитория
- `X-TFS-Proj-Name` — Название проекта
- `X-TFS-Group-Name` — Название группы

**Тело запроса (Git):**
```json
{
  "eventType": "git.push",
  "resource": {
    "commits": [
      {
        "commitId": "abc123",
        "author": {"name": "User", "email": "user@example.com"},
        "comment": "Commit message",
        "changes": [
          {"changeType": "edit", "item": {"path": "/src/main.cpp"}}
        ]
      }
    ],
    "refUpdates": [
      {
        "name": "refs/heads/master",
        "oldObjectId": "0000000000000000000000000000000000000000",
        "newObjectId": "abc123"
      }
    ],
    "repository": {"name": "ProjectName"}
  }
}
```

**Тело запроса (TFVC):**
```json
{
  "eventType": "tfvc.checkin",
  "resource": {
    "changesetId": 12345,
    "author": {"displayName": "User"},
    "comment": "Changeset comment",
    "changes": [
      {"changeType": "edit", "item": {"path": "$/Project/src/main.cpp"}}
    ]
  }
}
```

**Ответ:**
```json
{
  "status": "accepted",
  "message": "Webhook received"
}
```

**Rate Limit:** 30 запросов/минуту

---

### Проверка здоровья TFS веб-хука
```http
GET /webhook/health
```

Проверяет работоспособность TFS веб-хука.

**Ответ:**
```json
{
  "status": "ok",
  "service": "tfs-webhook",
  "timestamp": "2025-01-01T00:00:00"
}
```

**Rate Limit:** 120 запросов/минуту

---

### SonarQube веб-хук
```http
POST /sonarqube-webhook
Content-Type: application/json
```

Получает веб-хук от SonarQube.

**Заголовки:**
- `X-Sonar-Webhook-Id` — ID веб-хука
- `X-Sonar-Webhook-Timestamp` — Временная метка
- `X-Sonar-Webhook-HMAC-SHA256` — Подпись (если включено)

**Тело запроса:**
```json
{
  "serverUrl": "http://sonarqube",
  "taskId": "AXYZ123",
  "status": "SUCCESS",
  "analysedAt": "2025-01-01T00:00:00Z",
  "project": {
    "key": "project_key",
    "name": "Project Name"
  },
  "branch": {
    "name": "master",
    "type": "BRANCH",
    "isMain": true
  },
  "qualityGate": {
    "name": "Default Quality Gate",
    "status": "OK",
    "conditions": [
      {
        "metric": "new_coverage",
        "operator": "LT",
        "value": "85.5",
        "status": "OK",
        "errorThreshold": "80"
      }
    ]
  }
}
```

**Ответ:**
```json
{
  "status": "accepted",
  "message": "Webhook received and queued for processing",
  "project": "Project Name",
  "quality_gate_status": "OK",
  "task_id": "AXYZ123"
}
```

**Rate Limit:** 10 запросов/минуту

---

### Проверка здоровья SonarQube веб-хука
```http
GET /sonarqube-webhook/health
```

Проверяет работоспособность SonarQube веб-хука.

**Ответ:**
```json
{
  "status": "ok",
  "service": "sonarqube-webhook",
  "timestamp": "2025-01-01T00:00:00",
  "config": {
    "verify_signature": false,
    "has_secret": true
  }
}
```

**Rate Limit:** 120 запросов/минуту

---

## Миграция

### Мигрировать проекты
```http
GET /migrate-projects
```

Мигрирует существующие проекты из файловой системы в базу данных.

**Ответ:**
```json
{
  "message": "Project migration completed successfully",
  "migrated": 10,
  "skipped": 2,
  "errors": 0
}
```

---

## Проверка здоровья

### Здоровье приложения
```http
GET /health
```

Проверяет работоспособность приложения.

**Ответ:**
```json
{
  "status": "healthy",
  "service": "pvs-sonar-project-manager",
  "version": "2.0.0"
}
```

---

## Rate Limiting

Все эндпоинты ограничены по частоте запросов. При превышении лимита:

**Ответ (429 Too Many Requests):**
```json
{
  "detail": "Rate limit exceeded",
  "limit": "10/minute",
  "retry_after": "60"
}
```

**Заголовки:**
- `X-RateLimit-Limit` — Лимит запросов
- `X-RateLimit-Remaining` — Осталось запросов
- `Retry-After` — Секунд до сброса

### Лимиты по эндпоинтам

| Эндпоинт | Лимит |
|----------|-------|
| `/webhook` | 30/минуту |
| `/sonarqube-webhook` | 10/минуту |
| `/webhook/health` | 120/минуту |
| `/sonarqube-webhook/health` | 120/минуту |
| `/project/delete/*` | 5/минуту |
| `/project/analyze/*` | 10/минуту |
| `/` (форма) | 30/минуту |
| `/list` | 60/минуту |

---

## Ошибки

### 400 Bad Request
```json
{
  "detail": "Invalid payload format: ..."
}
```

### 401 Unauthorized
```json
{
  "detail": "Invalid credentials"
}
```

### 403 Forbidden
```json
{
  "detail": "Access denied. Admins only."
}
```

### 404 Not Found
```json
{
  "detail": "Project not found"
}
```

### 429 Too Many Requests
```json
{
  "detail": "Rate limit exceeded",
  "limit": "10/minute",
  "retry_after": "60"
}
```

### 500 Internal Server Error
```json
{
  "detail": "Internal server error: ..."
}
```

---

## OpenAPI Документация

Интерактивная документация API доступна по адресам:
- Swagger UI: `http://localhost:8080/docs`
- ReDoc: `http://localhost:8080/redoc`
