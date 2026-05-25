# Cursor — конфигурация PVS-Studio Tracker

Документация для агентов Cursor (не Qwen/Codex). Перед изменениями кода читайте файлы в порядке ниже.

## Порядок чтения

| Файл | Назначение |
|------|------------|
| [spec.md](spec.md) | Контракты: структура, модели, маршруты, diff, env |
| [rules.md](rules.md) | Жёсткие ограничения генерации кода |
| [context.md](context.md) | Архитектурные решения и trade-offs |
| [skills/pvs-tracker-dev/SKILL.md](skills/pvs-tracker-dev/SKILL.md) | Основной workflow агента |
| [CURSOR.md](../CURSOR.md) | Краткий обзор для людей и агентов |

## Skills

| Skill | Когда |
|-------|--------|
| `pvs-tracker-dev` | Любая работа в репозитории |
| `fix-parser` | Падение парсера PVS JSON |
| `add-htmx-filter` | Фильтры и `/ui/issues` |
| `add-api-route` | Маршруты `/api/v2` и `/api/v1` |

Метаданные: [skills.json](skills.json).

## Prompts (шаблоны задач)

- [prompts/fix_parser.md](prompts/fix_parser.md)
- [prompts/add_ui_filter.md](prompts/add_ui_filter.md)
- [prompts/add_route.md](prompts/add_route.md)

## MCP

[mcp.json](mcp.json) — filesystem, sqlite, fetch.

## Запуск

```bash
uvicorn pvs_tracker.main:app --reload --host 0.0.0.0 --port 8080
```

API v2 login: `POST /api/v2/auth/login` (пользователь `admin` создаётся при старте, пароль из БД). UI login (`POST /login`) пока принимает любые непустые credentials (MVP).

Профиль: `/ui/settings/profile`, `PATCH /api/v2/users/me`. Email после API upload: `notifications.py` + `SMTP_*` в `.env`.
