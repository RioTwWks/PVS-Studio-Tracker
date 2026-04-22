# Правила генерации кода для PVS-Tracker

> ⚙️ Этот файл содержит строгие директивы для Qwen CLI. Все сгенерированные файлы, рефакторинг и архитектурные решения должны соответствовать данным правилам. Нарушение приводит к немедленному переписыванию кода.

---

## 🎯 1. Контекст и цель
- **Проект:** Автономный трекер предупреждений PVS-Studio с инкрементальной аналитикой.
- **Замена SonarQube:** Упор на быструю загрузку JSON-отчётов, diff между запусками, LDAP-авторизацию и нативный деплой.
- **Приоритет:** Стабильность > Скорость разработки > Фичи. Никакого "магического" кода.

---

## 📐 2. Архитектурные ограничения
| Правило | Детали |
|---------|--------|
| **Без Docker** | Запуск как системная служба (`systemd` / `WinSW`/`NSSM`). Все пути относительные или из `.env`. |
| **БД** | SQLite для dev, PostgreSQL для prod. Движок инициализируется один раз в `db.py`. Миграции не требуются в v1 (авто-создание таблиц через `SQLModel.metadata.create_all`). |
| **Очереди** | Только `FastAPI.BackgroundTasks`. **Запрещено**: Celery, RQ, Redis, Kafka в v1. |
| **Async/Sync** | `async def` для HTTP-эндпоинтов. БД-операции выполняются в потоке через `SQLModel` (синхронный `Session` с `yield`). `httpx` для вебхуков. |
| **Модульность** | Один файл = одна ответственность. Не объединять `models.py`, `parser.py`, `auth.py`, `classifier_parser.py`. |
| **Error Classifier** | `ErrorClassifier` таблица заполняется из `Actual_warnings.csv` при старте. Issues автоматически линкуются по `rule_code` в `incremental.py`. |

---

## 🐍 3. Python & Backend стандарты
- **Type Hints:** Обязательны везде. `def func(x: str) -> dict[str, Any]:`
- **Pydantic v2:** Используется для конфигов, запросов/ответов API. Валидация на входе, не в бизнес-логике.
- **SQLModel:**
  - Все модели наследуют `SQLModel, table=True`
  - Внешние ключи через `Field(foreign_key="table.id")`
  - Индексы: `fingerprint`, `run_id`, `status`, `project_id`, `rule_code` (ErrorClassifier)
  - `Issue.classifier_id` — nullable FK to `ErrorClassifier.id`
- **Логирование:** `import logging`. `logger = logging.getLogger(__name__)`. **Запрещено** `print()`.
- **Обработка ошибок:** `HTTPException(status_code=..., detail="...")` для API. Для UI — редирект на `/login` или страница ошибки с `status_code`.
- **Зависимости FastAPI:** `Depends(get_session)`, `Depends(require_auth)`. Не создавать сессии вручную в роутах.

---

## 🌐 4. Frontend (Jinja2 + HTMX) правила
- **Наследование:** Все шаблоны расширяют `base.html`. Никаких дубликатов `<head>`/`<nav>`.
- **HTMX-фрагменты:**
  - Возвращают **только** HTML-кусок (например, `<table>...</table>`).
  - Не содержат `<!DOCTYPE>`, `<html>`, `<script>` (кроме инлайн-обработчиков, если неизбежно).
  - `hx-target` всегда указывает на конкретный `id`.
- **Upload Forms:**
  - Формы в UI используют `/ui/upload`, который **редиректит на дашборд** (303)
  - API endpoint `/api/v1/upload` возвращает JSON для CI/CD и скриптов
  - Никогда не возвращать JSON из UI форм — всегда redirect
- **Пагинация & Фильтры:**
  - Состояние передаётся в URL query params.
  - При клике "Вперёд" HTMX подгружает `/ui/issues?page=N&severity=...` и заменяет `#issues-table`.
  - Текущие фильтры сохраняются в кнопках пагинации.
- **Chart.js:** Инициализируется один раз в `dashboard.html`. Данные сериализуются через `{{ history | tojson }}`.
- **Безопасность шаблонов:** `{{ variable }}` экранируется автоматически. Для HTML `{{ safe_html | safe }}` только после явной санитизации.

---

## 🔐 5. Безопасность и LDAP
- **LDAP Bind:** Прямая проверка `username@domain` + пароль. При неудаче → `401`. Никаких кеширования паролей.
- **Сессии:** `SessionMiddleware(secret_key=SECRET_KEY, https_only=True, same_site="lax")`.
- **Хранение юзера:** `request.session["user"] = {"username": str, "display_name": str}`.
- **CSRF:** HTMX автоматически отправляет `X-Requested-With: XMLHttpRequest`. Для мутаций (`POST/PUT/DELETE`) проверять `Origin`/`Referer` или использовать `SameSite=Strict` в production.
- **Secrets:** Никогда не хардкодить. Только `config.py` → `.env`. `.env` в `.gitignore`.

---

## 🧠 6. Инкрементальная логика и парсинг
- **Фингерпринт:**
  ```python
  norm_file = file.replace("\\", "/").strip()
  norm_msg = " ".join(message.split())
  fp = hashlib.sha256(f"{norm_file}:{line}:{code}:{norm_msg}".encode()).hexdigest()[:16]
  ```
- **Diff-алгоритм:**
  1. Загрузить `current_fps` из нового отчёта.
  2. Получить `prev_fps` из последнего `Run.status == "done"`.
  3. Классификация в одной транзакции:
     - `∉ prev_fps` → создать `Issue` в **текущем** run со `status="new"`
     - `∈ prev_fps` → создать `Issue` в **текущем** run со `status="existing"`
     - `prev_fps - current_fps` → создать **новый** `Issue` в **текущем** run со `status="fixed"` (НЕ менять записи предыдущего run!)
  4. `session.commit()` только после всех операций.
- **Error Classifier Linkage:**
  - При создании `Issue` в `classify_and_store()`, автоматически линкуется `classifier_id` по `rule_code`
  - Строится словарь `{rule_code: classifier_id}` из таблицы `ErrorClassifier`
  - Если `rule_code` не найден, `classifier_id` остаётся `None`
- **Устойчивость парсера:** PVS JSON меняет поля между версиями. Использовать `.get()`, fallback'ы, `try/except KeyError`. Не падать при неизвестных ключах.

---

## 🤖 7. Правила генерации для Qwen CLI
| Требование | Инструкция для AI |
|------------|-------------------|
| **Фазы** | Строго следовать `spec.md` Phase 1 → 6. Не генерировать Phase 3, пока не подтверждена работа Phase 2. |
| **Контекст** | Перед генерацией читать `spec.md`, `.qwen/rules.md`, текущие файлы. Не дублировать логику. |
| **Вывод кода** | Всегда отдавать **полный файл** при изменении. Указывать имя файла в начале блока. |
| **Проверка** | После каждого этапа давать команду для запуска/теста. Если ошибка — фиксить, а не продолжать. |
| **Комментарии** | Только если логика неочевидна. На русском. Docstrings по Google-style. |
| **Зависимости** | Указывать новые `pip install` команды явно. Не добавлять без согласования. |

---

## 🚫 8. Запреты и антипаттерны
```text
🔴 НИКОГДА:
- Использовать print() для логирования или отладки в production-коде
- Хардкодить пути, пароли, URL, секретные ключи
- Создавать Dockerfile, docker-compose.yml, .gitignore с docker-артефактами
- Добавлять Redis, Celery, RQ, Kafka в v1
- Использовать eval(), exec(), os.system(), subprocess.call без sandbox
- Возвращать HTML из /api/* маршрутов
- Игнорировать type hints или использовать Any без обоснования
- Делать синхронные HTTP-запросы в async-эндпоинтах
- Менять статус "fixed" у записей предыдущего run (создавать новые записи в текущем run!)
- Считать "total" как сумму new+existing одного run (использовать кумулятивную логику!)
```

---

## 🔄 9. Workflow взаимодействия
1. **Запрос:** Указывай фазу, файл, ожидаемый интерфейс. Пример:  
   `Phase 2: Создай incremental.py с функцией classify_and_store. Используй модели из spec.md.`
2. **Ответ AI:** Отдаёт полный файл, объясняет ключевые решения, даёт команду проверки.
3. **Валидация:** Запускаешь `uvicorn main:app --reload`, проверяешь лог, тестируешь curl/HTMX.
4. **Ошибка:** Прикладываешь трейсбэк, запрос, ответ сервера. AI фиксит и переотдаёт файл.
5. **Утверждение:** После успешного теста пишешь `✅ Phase X подтверждена. Переходим к Phase Y.`

---

## 📌 10. Чек-лист перед коммитом
- [ ] `uvicorn main:app` запускается без ошибок
- [ ] Все импорты разрешимы, нет `ModuleNotFoundError`
- [ ] `SECRET_KEY` и `DATABASE_URL` берутся из `.env`
- [ ] `/api/*` возвращают JSON, `/ui/*` возвращают HTML
- [ ] HTMX-таблица пагинируется и фильтруется без перезагрузки
- [ ] Webhook отправляется асинхронно после обработки
- [ ] LDAP-авторизация блокирует доступ к `/ui/*` без сессии
- [ ] Инкрементальный diff корректно ставит `new`/`fixed`/`existing`
- [ ] ErrorClassifier загружается из CSV при старте
- [ ] Issues корректно линкуются к ErrorClassifier по rule_code
- [ ] UI отображает classifier type/priority badges
- [ ] Нет `print()`, нет хардкодов, все типы указаны
