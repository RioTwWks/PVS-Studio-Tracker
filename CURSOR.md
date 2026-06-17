# PVS-Studio Tracker — Cursor Project Guide

Incremental PVS-Studio report tracker (FastAPI + SQLModel + HTMX). This file is the human/agent entry point; detailed contracts live in `.cursor/`.

## Quick links

| Doc | Purpose |
|-----|---------|
| [.cursor/README.md](.cursor/README.md) | Index for Cursor config |
| [.cursor/spec.md](.cursor/spec.md) | Routes, models, diff, env |
| [.cursor/rules.md](.cursor/rules.md) | Code generation constraints |
| [.cursor/context.md](.cursor/context.md) | Architecture decisions |
| [docs/README.md](docs/README.md) | User docs index (API, CI, code viewer) |
| [README.md](README.md) | Product overview and install |

## Run

```bash
pip install -e ".[dev]"
python migrate.py          # if upgrading DB
uvicorn pvs_tracker.main:app --reload --host 0.0.0.0 --port 8080
```

- **Login** (`POST /login`, `POST /api/v2/auth/login`): `authenticate_credentials` — локальный `User` (bcrypt) или LDAP (`LDAP_ENABLED=true`, `auth.py`).
- Сессия: `user_id` + `user` (username). Новые LDAP-пользователи → роль Viewer.
- **API v2**: пользователь `admin` / `admin` создаётся при `migrate.py` / первом старте (сменить в production).

## Package layout

```
pvs_tracker/
├── main.py              # v1 routes, dashboard, upload
├── api.py               # /api/v2 REST (JWT, RBAC, profile, QG rules)
├── project_manage.py    # /ui/projects/new, CI HTMX, toggles
├── project_ci.py        # Sonar form → Project fields
├── inbound_webhooks.py, jenkins_service.py, jira_sync.py
├── auth_service.py      # Users, JWT, session → User
├── incremental.py       # diff per target_platform
├── platforms.py         # OS + cross_platform_fp
├── dashboard_context.py # platform-scoped dashboard metrics
├── notifications.py     # SMTP on API upload
├── quality_gate.py      # rule-code quality gates
├── issue_author.py      # author_name/email on issues (Sonar-style)
├── upload_metadata.py   # .meta.json commit author from CI
├── warnings_catalog.py  # sync ErrorClassifier from pvs-studio.com
├── project_groups.py    # ProjectGroup + home grouping
├── security.py          # bcrypt, technical debt helpers
├── code_viewer.py, webhooks.py, git_integration.py, ...
├── templates/
│   ├── home.html        # grouped projects, color cards
│   ├── projects/        # project_form, _form_fields
│   └── dashboard/       # tabs incl. _ci_*, _settings_*
static/app.js            # toast (sq-toast), i18n, inline code toggle
```

## Core behavior

### Upload

- `POST /ui/upload` — form → **303** → `/ui/projects/{id}/dashboard`
- `POST /api/v1/upload` — multipart JSON → JSON (session auth)
- **`report_type`**: `incremental` (default) | `full` — scope diff; хранится в `Run.report_type`
- Опционально: `commit_metadata` (`.meta.json`) или поля формы — `commit`, `commit_author_name`, `commit_author_email`, `report_type` (`upload_metadata.py`)

### Incremental diff

- Fingerprint: SHA-256[:16] of `file:line:code:message` (paths `\` → `/`).
- **new** / **existing**: new `Issue` rows in the **current** run.
- **fixed**: only when `report_type=full` — disappeared fingerprints → new `Issue` in **current** run with `status=fixed` (previous run rows unchanged).
- **`report_type=incremental`**: missing warnings in JSON are **not** marked `fixed` (partial PVS report).
- **Author:** `issue_author.resolve_issue_author` — `new` → автор коммита run; `existing`/`fixed` → из prev issue.
- `prev_fps` excludes `ignored` and `fixed` from the previous run.
- Prev run: latest `done` for same `target_platform` (**not** by UI branch).
- Upload form accepts `target_platform` (`windows` / `linux` / `macos`).

### Ignore

`POST /api/v1/issues/{fingerprint}/ignore` sets `Issue.status = "ignored"` (no separate table).

### Dashboard

- Tabs: Overview, Issues, Code, Trends, **Analysis / CI**, Upload, **Settings** (sub-tabs: CI params, source roots, quality gate).
- **Analysis / CI:** HTMX → `#project-ci-panel`; toast from `#ci-toast-payload` in response + `handleCiToastFromResponseText` in `app.js` (do not use bootstrap `.toast` class).
- **Home:** project cards by group; colors per `disabled` / `disable_jira`.
- **New project:** `/ui/projects/new` → `POST /ui/projects/create`.
- Delete project: header button on dashboard (admin).
- Branch: `?branch=`; platform: `platform-metrics` + `trends-fragment`; `?tab=` / `?settings_tab=`.
- Trend `total`: cumulative active count (`dashboard_history.py`).

### Profile & email

- UI: `/ui/settings/profile` — name, email, API upload notification projects.
- API: `PATCH /api/v2/users/me`, `PUT /api/v2/users/me/notifications`.
- Email: after successful `POST /api/v1/upload` only (`notifications.py`, `SMTP_*` in `.env`).

### Quality gates (current)

- Gate = set of PVS `rule_code` (`QualityGateRule`); fails if any **new** issue in scope.
- UI admin: `/ui/settings/quality-gates`; API: `/api/v2/quality-gates` (+ `PUT` rules on gate).

### Code viewer

- Inline: Code tab + `GET /ui/file`
- Standalone: `/ui/projects/{id}/code-viewer`
- Sources: git, archive, filesystem via `file_resolver.py`

### Webhooks

- Env: `WEBHOOK_URL`, `WEBHOOK_SECRET`
- Events: `report_uploaded`, `quality_gate_evaluated`

## API surface (short)

| Area | Prefix | Auth |
|------|--------|------|
| UI + v1 | `/`, `/ui/*`, `/api/v1/*` | Mixed (see spec) |
| v2 REST | `/api/v2/*` | JWT / session User |

Full route tables: `.cursor/spec.md`.

## Environment

| Variable | Used in |
|----------|---------|
| `DATABASE_URL` | `db.py` |
| `SECRET_KEY` | Session middleware |
| `JWT_SECRET_KEY` | `auth_service.py` |
| `WEBHOOK_URL`, `WEBHOOK_SECRET` | `webhooks.py` |
| `WEBHOOK_USERNAME`, `WEBHOOK_PASSWORD` | `inbound_webhooks.py` |
| `JENKINS_*` | `jenkins_service.py` |
| `JIRA_*` | `jira_service.py`, `jira_sync.py` |
| `SMTP_*`, `APP_BASE_URL` | `notifications.py` |
| `GIT_*`, `SNAPSHOTS_DIR` | `git_integration.py` |
| `LDAP_*` | `auth.py` (via `auth_service.authenticate_credentials`) |

See `.env.example`. User docs: [docs/README.md](docs/README.md). CI: [docs/jenkins-ci.md](docs/jenkins-ci.md).

## Tests

```bash
pytest
pytest tests/test_smoke.py tests/test_parser.py -v
pytest tests/test_ci_integration.py -q   # HTMX CI toggles, inbound webhook, Jira
pytest tests/test_auth_local.py tests/test_auth_ldap.py -q
pytest tests/test_upload_metadata.py tests/test_issue_author.py -q
pytest tests/test_warnings_catalog.py -q
```

## Agent skills

- `@pvs-tracker-dev` — default project work
- `@fix-parser` — PVS JSON parser
- `@add-htmx-filter` — issues table filters
- `@add-api-route` — `/api/v2` or `/api/v1` endpoints

## Known doc/code gaps (intentional notes)

- UI routes for dashboard/issues/code viewer are open without login (read-only).
- Incremental diff ignores branch; UI branch filter is display-only for history.
- Diff по branch — не реализован (только `target_platform`).
