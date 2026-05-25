# PVS-Studio Tracker — Cursor Project Guide

Incremental PVS-Studio report tracker (FastAPI + SQLModel + HTMX). This file is the human/agent entry point; detailed contracts live in `.cursor/`.

## Quick links

| Doc | Purpose |
|-----|---------|
| [.cursor/README.md](.cursor/README.md) | Index for Cursor config |
| [.cursor/spec.md](.cursor/spec.md) | Routes, models, diff, env |
| [.cursor/rules.md](.cursor/rules.md) | Code generation constraints |
| [.cursor/context.md](.cursor/context.md) | Architecture decisions |
| [README.md](README.md) | User-facing docs (features, API examples) |

## Run

```bash
pip install -e ".[dev]"
python migrate.py          # if upgrading DB
uvicorn pvs_tracker.main:app --reload --host 0.0.0.0 --port 8080
```

- **UI login** (`/login`): any non-empty username/password → session cookie (MVP).
- **API v2** (`POST /api/v2/auth/login`): DB user `admin` / `admin` created on first startup (change in production).

## Package layout

```
pvs_tracker/
├── main.py              # v1 routes, dashboard, upload
├── api.py               # /api/v2 REST (JWT, RBAC, profile, QG rules)
├── auth_service.py      # Users, JWT, session → User
├── incremental.py       # diff per target_platform
├── platforms.py         # OS + cross_platform_fp
├── dashboard_context.py # platform-scoped dashboard metrics
├── notifications.py     # SMTP on API upload
├── quality_gate.py      # rule-code quality gates
├── warnings_catalog.py  # PVS catalog sync (api v2)
├── code_viewer.py, webhooks.py, git_integration.py, ...
└── templates/dashboard/ # tabs + _platform_switcher, _trends_content
```

## Core behavior

### Upload

- `POST /ui/upload` — form → **303** → `/ui/projects/{id}/dashboard`
- `POST /api/v1/upload` — multipart JSON → JSON (session auth)

### Incremental diff

- Fingerprint: SHA-256[:16] of `file:line:code:message` (paths `\` → `/`).
- **new** / **existing**: new `Issue` rows in the **current** run.
- **fixed**: disappeared fingerprints → new `Issue` in **current** run with `status=fixed` (previous run rows unchanged).
- `prev_fps` excludes `ignored` and `fixed` from the previous run.
- Prev run: latest `done` for same `target_platform` (**not** by UI branch).
- Upload form accepts `target_platform` (`windows` / `linux` / `macos`).

### Ignore

`POST /api/v1/issues/{fingerprint}/ignore` sets `Issue.status = "ignored"` (no separate table).

### Dashboard

- Tabs: Overview, Issues, Code, Trends, Upload, Settings.
- Branch switcher: `?branch=` filters chart + issues table.
- **Platform switcher** (Windows/Linux/macOS): updates KPIs/chart via `platform-metrics` + `trends-fragment` without full reload.
- Trend `total` in history: cumulative active count (`dashboard_history.py`, see `spec.md`).

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
| `SMTP_*`, `APP_BASE_URL` | `notifications.py` |
| `GIT_*`, `SNAPSHOTS_DIR` | `git_integration.py` |

See `.env.example`.

## Tests

```bash
pytest
pytest tests/test_smoke.py tests/test_parser.py -v
```

## Agent skills

- `@pvs-tracker-dev` — default project work
- `@fix-parser` — PVS JSON parser
- `@add-htmx-filter` — issues table filters
- `@add-api-route` — `/api/v2` or `/api/v1` endpoints

## Known doc/code gaps (intentional notes)

- UI routes for dashboard/issues are open without login; tighten when LDAP lands.
- Incremental diff ignores branch; UI branch filter is display-only for history.
- UI `POST /login` is MVP (any credentials); profile API needs a matching `User` row in DB.
