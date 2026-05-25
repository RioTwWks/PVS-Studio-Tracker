---
name: pvs-tracker-dev
description: >-
  Develops and maintains PVS-Studio Tracker (FastAPI, SQLModel, HTMX, API v2,
  quality gates, incremental PVS JSON diff). Use when working in this repo,
  uploads, parser, UI, webhooks, auth_service, or deployment.
---

# PVS-Studio Tracker — Agent Skill

Приоритет: **стабильность > скорость > фичи**.

## Before coding

1. [.cursor/spec.md](../../spec.md) — routes, models, diff contract
2. [.cursor/rules.md](../../rules.md) — hard limits
3. [.cursor/context.md](../../context.md) — trade-offs
4. [CURSOR.md](../../../CURSOR.md) — quick orientation

### Focused sub-skills

| Skill | When |
|-------|------|
| [fix-parser](../fix-parser/SKILL.md) | Parser / PVS JSON format |
| [add-htmx-filter](../add-htmx-filter/SKILL.md) | `/ui/issues` filters & HTMX |
| [add-api-route](../add-api-route/SKILL.md) | `/api/v2` or `/api/v1` endpoints |

## Stack (actual)

- Package: `pvs_tracker/` (not root `main.py`)
- Run: `uvicorn pvs_tracker.main:app --reload`
- No `config.py` — env in `db.py`, `main.py`, `auth_service.py`, `webhooks.py`
- Reports stored in DB (`RunReport`), not `reports/` folder

## Auth (do not assume LDAP is active)

| Layer | Behavior |
|-------|----------|
| UI `POST /login` | MVP: non-empty credentials → `session["user"]` = username string |
| UI protected | upload, create project, global settings — `require_auth` |
| UI open | dashboard, `/ui/issues`, code viewer (current code) |
| API v2 | JWT + `User` table via `auth_service.py` |
| `auth.py` | LDAP stub, **not** used by `main.py` |

## Incremental diff (authoritative)

In `incremental.classify_and_store`:

- Fixed → **new** `Issue` rows in **current** `run_id`, `status="fixed"`
- Do **not** update previous run issues
- `prev_fps` excludes `ignored` and `fixed`
- Prev run: last `done` for project (no branch filter in diff yet)

## Upload

- UI: `POST /ui/upload` → 303 dashboard
- API: `POST /api/v1/upload` → JSON

## Webhooks

- `WEBHOOK_URL` / `WEBHOOK_SECRET`
- Events: `report_uploaded`, `quality_gate_evaluated`
- `httpx` async in `webhooks.py`

## MCP

| Server | Use |
|--------|-----|
| filesystem | Templates, Python modules |
| sqlite | Schema, diff debugging |
| fetch | API + HTMX HTML checks |

## Delivery protocol

1. Minimal diff; match existing style
2. Type hints; `logging`, not `print()`
3. End with:

```text
✅ Файл готов. Запусти: <команда>
Ожидаемый результат: <описание>
```

## Banned

Celery, Redis, Kafka, Docker, Alembic (unless agreed), `IgnoredIssue` table.

## More detail

- [reference.md](reference.md) — env, deployment
- [patterns.md](patterns.md) — pytest, HTMX patterns
