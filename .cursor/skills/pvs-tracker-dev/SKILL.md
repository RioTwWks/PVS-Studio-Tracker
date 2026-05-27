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
5. [docs/README.md](../../../docs/README.md) — user docs index

### Focused sub-skills

| Skill | When |
|-------|------|
| [fix-parser](../fix-parser/SKILL.md) | Parser / PVS JSON format |
| [add-htmx-filter](../add-htmx-filter/SKILL.md) | `/ui/issues` filters & HTMX |
| [add-api-route](../add-api-route/SKILL.md) | `/api/v2` or `/api/v1` endpoints |

## Stack (actual)

- Package: `pvs_tracker/` (not root `main.py`)
- Run: `uvicorn pvs_tracker.main:app --reload`
- No `config.py` — env in `db.py`, `main.py`, `auth_service.py`, `webhooks.py`, `notifications.py`
- Reports stored in DB (`RunReport`), not `reports/` folder

## Auth

| Layer | Behavior |
|-------|----------|
| UI `POST /login` | `authenticate_credentials` → `establish_session` (`user_id` + username) |
| LDAP | `auth.py` — `LDAP_*` in `.env`, SIMPLE/NTLM; JIT `User`, роль Viewer |
| Upload metadata | `commit_metadata` file or form fields → `Run.commit_author_*` (`upload_metadata.py`) |
| Issue author | `issue_author.resolve_issue_author` in `incremental.py` |
| Project groups | `ProjectGroup` + `/api/v2/admin/groups`; `project_groups.get_group_choices` |
| Warnings sync | `POST /api/v2/warnings/sync` → `warnings_catalog.py` |
| UI protected | upload, create project, profile, global/QG settings — `require_auth` / `require_admin` |
| UI open | dashboard, `/ui/issues`, code viewer (current code) |
| API v2 | JWT + session cookie + `auth_service.py` |
| Users admin UI | `/ui/settings/global` → tab Users & Permissions |

## Incremental diff (authoritative)

In `incremental.classify_and_store`:

- Fixed → **new** `Issue` rows in **current** `run_id`, `status="fixed"`
- Do **not** update previous run issues
- `prev_fps` excludes `ignored` and `fixed`
- Prev run: last `done` for same `project_id` + `target_platform` (no branch filter in diff yet)
- `cross_platform_fp` in `platforms.py` for path matching across OS

## Upload

- UI: `POST /ui/upload` → 303 dashboard (`target_platform` form field)
- API: `POST /api/v1/upload` → JSON; triggers `schedule_api_upload_notifications`

## Profile & notifications

- `GET/PATCH /api/v2/users/me`, `GET/PUT /api/v2/users/me/notifications`
- UI `/ui/settings/profile`; model `UserProjectNotification`
- SMTP: `SMTP_HOST`, … — see `notifications.py`

## Webhooks

- `WEBHOOK_URL` / `WEBHOOK_SECRET` — outbound after upload / QG
- Events: `report_uploaded`, `quality_gate_evaluated`
- `httpx` async in `webhooks.py`

## CI / SAST (монолит)

| Module | Role |
|--------|------|
| `inbound_webhooks.py` | `POST /webhook/inbound` (TFS/Git) |
| `jenkins_service.py` | Trigger job, `SONAR_*` param aliases |
| `project_ci.py` | `parse_sonar_form_fields`, create/update project |
| `project_manage.py` | UI routes, HTMX CI panel, `#ci-toast-payload` |
| `jira_sync.py` | Issues after upload |

UI: `home.html` (colored cards), `projects/_form_fields.html`, `dashboard/_ci_*.html`.  
Toast: `showToast` in `app.js` — **no** bootstrap class `toast` (hidden without `.show`).  
Inline Code (Issues): `issue_row.html` + `toggleInlineCode` / `closeInlineCodeRow` in `app.js`.  
Tests: `tests/test_ci_integration.py`.

See [docs/jenkins-ci.md](../../docs/jenkins-ci.md).

## Quality gates

- Rule-code sets (`QualityGateRule`), not metric thresholds only
- `evaluate_quality_gate` — fail if new issue `rule_code` in gate scope

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
