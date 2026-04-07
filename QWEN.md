# PVS-Studio Tracker — Project Context

## Project Overview

**PVS-Studio Tracker** is an incremental static analysis report tracker for PVS-Studio. It is a FastAPI-based web application that allows teams to upload PVS-Studio JSON reports, track warnings over time, and visualize trends (new, existing, and fixed issues) across commits and branches.

### Core Features
- **Report Upload** — REST API `POST /api/v1/upload` accepts PVS-Studio JSON reports with project name, commit, and branch
- **Incremental Classification** — Each warning gets a stable fingerprint (SHA-256 of `file:line:code:message`), enabling tracking across runs: **new**, **existing**, **fixed**, **ignored**
- **Dashboard** — `GET /api/v1/projects/{id}/dashboard` returns trend data for the last 10 runs
- **Web UI** — Jinja2 templates with HTMX + Bootstrap + Chart.js for interactive dashboards
- **Auth** — Simple bypass auth for MVP (accepts any credentials); LDAP stub in `auth.py`
- **False Positive Management** — `POST /api/v1/issues/{fingerprint}/ignore` marks issues as ignored

### Architecture

```
pvs_tracker/
├── __init__.py
├── main.py           # FastAPI app, all routes, DB init
├── models.py         # SQLModel: Project, Run, Issue
├── parser.py         # PVS-Studio JSON parser + fingerprinting
├── incremental.py    # Classification logic (new/existing/fixed)
├── auth.py           # LDAP auth helpers (stub)
└── templates/
    ├── base.html         # Base layout (Bootstrap + HTMX + Chart.js)
    ├── home.html         # Home: projects list + upload form
    ├── login.html        # Login page
    ├── dashboard.html    # Dashboard with trend chart
    └── issues_table.html # Issues table with filters & pagination
tests/
├── conftest.py       # pytest fixtures
└── test_smoke.py     # Smoke tests
```

### Tech Stack
- **Python 3.10+**
- **FastAPI** + **Uvicorn** — web framework and ASGI server
- **SQLModel** — ORM (SQLite by default)
- **Pydantic** — data validation
- **Jinja2** — template rendering
- **HTMX + Bootstrap + Chart.js** — frontend
- **ldap3** — LDAP/AD authentication
- **pytest** — testing

---

## Building and Running

### Setup
```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -e ".[dev]"
```

### Run the Server
```bash
uvicorn pvs_tracker.main:app --reload --host 0.0.0.0 --port 8080
```

Open http://localhost:8080 — login with any credentials (MVP mode).

### Run Tests
```bash
pytest
pytest tests/test_smoke.py -v   # smoke tests
```

### Linting & Type Checking
```bash
ruff check .
mypy .
```

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/login` | Login (accepts any credentials in MVP) |
| `GET`  | `/logout` | Logout |
| `GET`  | `/` | Home page (projects list + upload form) |
| `POST` | `/api/v1/upload` | Upload PVS-Studio JSON report |
| `GET`  | `/api/v1/projects/{id}/dashboard` | Dashboard JSON |
| `GET`  | `/ui/projects/{id}/dashboard` | Dashboard HTML |
| `GET`  | `/ui/issues?project_id={id}` | Issues table HTML |
| `POST` | `/api/v1/issues/{fingerprint}/ignore` | Mark as false positive |

---

## Database Schema

| Model | Fields |
|-------|--------|
| **Project** | `id`, `name` (unique), `language`, `created_at` |
| **Run** | `id`, `project_id` (FK), `timestamp`, `commit`, `branch`, `report_file`, `status` |
| **Issue** | `id`, `run_id` (FK), `fingerprint`, `file_path`, `line`, `rule_code`, `severity`, `message`, `status` |

---

## Key Design Decisions

- **Fingerprinting**: SHA-256 hash of normalized `file:line:code:message` for stable issue tracking
- **Incremental Analysis**: Compares against the previous successful run to classify as new/existing/fixed
- **SQLite default**: Simple setup; swappable via `DATABASE_URL` env var
- **HTMX UI**: Server-rendered templates with dynamic updates, no SPA framework
- **MVP Auth**: Any credentials accepted; replace with LDAP via `auth.py` for production

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./pvs_tracker.db` | Database connection string |
| `SECRET_KEY` | `dev-change-me` | Session cookie signing key |

---

## Development Conventions

- **Line length**: 100 characters
- **Indentation**: 4 spaces (Python), 2 spaces (HTML/JS/CSS)
- **Type hints**: strict mode via mypy
- **Imports**: sorted by Ruff (`I` rule)
- **Testing**: use `tests/conftest.py` fixtures; smoke tests in `tests/test_smoke.py`
