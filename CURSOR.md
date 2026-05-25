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
├── main.py           # v1 routes, dashboard, upload, ui_issues
├── api.py            # /api/v2 REST (JWT, RBAC, quality gates)
├── auth_service.py   # Users, JWT, session → User
├── auth.py           # LDAP stub (not wired to main login)
├── models.py         # SQLModel tables
├── parser.py         # PVS JSON modern + legacy
├── incremental.py    # new / existing / fixed
├── code_viewer.py    # /ui/file, code-viewer page
├── quality_gate.py, webhooks.py, git_integration.py, ...
└── templates/dashboard/   # 6 tabs + partials
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
- Prev run selection: latest `done` for project (**not** filtered by UI branch).

### Ignore

`POST /api/v1/issues/{fingerprint}/ignore` sets `Issue.status = "ignored"` (no separate table).

### Dashboard

- Tabs: Overview, Issues, Code, Trends, Upload, Settings.
- Branch switcher: `?branch=` filters chart + issues table.
- Trend `total` in history: cumulative active count logic in `main.py` (see `spec.md`).

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
