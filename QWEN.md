# PVS-Studio Tracker — Project Context

## Project Overview

**PVS-Studio Tracker** is an incremental static analysis report tracker for PVS-Studio. It is a FastAPI-based web application that allows teams to upload PVS-Studio JSON reports, track warnings over time, and visualize trends (new, existing, and fixed issues) across commits and branches.

### Core Features
- **Report Upload** — Two endpoints:
  - **UI**: `POST /ui/upload` accepts form data and **redirects to project dashboard** (HTTP 303)
  - **API**: `POST /api/v1/upload` accepts PVS-Studio JSON reports with project name, commit, and branch (returns JSON)
- **Incremental Classification** — Each warning gets a stable fingerprint (SHA-256 of `file:line:code:message`), enabling tracking across runs: **new**, **existing**, **fixed**, **ignored**
- **Error Classifier** — Automatically links issues to `ErrorClassifier` table (loaded from `Actual_warnings.csv` on startup) with `type`, `priority`, and description metadata
- **Dashboard** — `GET /api/v1/projects/{id}/dashboard` returns trend data for the last 10 runs with classifier summary statistics
- **Web UI** — Jinja2 templates with HTMX + Bootstrap + Chart.js for interactive dashboards, displays classifier type/priority badges
- **Auth** — Simple bypass auth for MVP (accepts any credentials); LDAP stub in `auth.py`
- **False Positive Management** — `POST /api/v1/issues/{fingerprint}/ignore` marks issues as ignored

### Architecture

```
pvs_tracker/
├── __init__.py
├── main.py           # FastAPI app, all routes, DB init
├── models.py         # SQLModel: Project, Run, Issue, ErrorClassifier
├── parser.py         # PVS-Studio JSON parser + fingerprinting
├── incremental.py    # Classification logic (new/existing/fixed)
├── classifier_parser.py  # CSV classifier parser (Actual_warnings.csv)
├── auth.py           # LDAP auth helpers (stub)
└── templates/
    ├── base.html         # Base layout (Bootstrap + HTMX + Chart.js + dark theme + i18n)
    ├── home.html         # Home: projects list + upload form
    ├── login.html        # Login page
    ├── dashboard.html    # Dashboard with trend chart + stat cards + filters
    └── issues_table.html # Issues table with filters & pagination (HTMX partial, shows classifier info)
static/
├── style.css             # Custom CSS with CSS variables, dark theme (dark blue), transitions
├── app.js                # ThemeManager, I18n (RU/EN), Chart.js wrapper, animated counters, toasts
└── translations.json     # Bilingual strings (ru/en) keyed by i18n identifiers
tests/
├── conftest.py           # pytest fixtures
├── test_smoke.py         # Smoke tests
└── test_classifier.py    # Error classifier tests
```

### Tech Stack
- **Python 3.10+**
- **FastAPI** + **Uvicorn** — web framework and ASGI server
- **SQLModel** — ORM (SQLite by default)
- **Pydantic** — data validation
- **Jinja2** — template rendering
- **HTMX + Bootstrap 5 + Chart.js + Bootstrap Icons** — frontend
- **Custom JS (`static/app.js`)** — `ThemeManager` (light/dark blue), `I18n` (RU/EN toggle), Chart.js wrapper, animated counters, toast notifications
- **Custom CSS (`static/style.css`)** — CSS custom properties, dark blue theme, smooth transitions, severity/status styling, responsive design
- **i18n (`static/translations.json`)** — Bilingual string file (ru/en), client-side via `data-i18n` attributes
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
| `POST` | `/ui/upload` | **UI form upload** — accepts form data, **redirects to dashboard** (303) |
| `POST` | `/api/v1/upload` | **API upload** — accepts JSON report, returns JSON response |
| `GET`  | `/api/v1/projects/{id}/dashboard` | Dashboard JSON |
| `GET`  | `/ui/projects/{id}/dashboard` | Dashboard HTML |
| `GET`  | `/ui/issues?project_id={id}` | Issues table HTML |
| `POST` | `/api/v1/issues/{fingerprint}/ignore` | Mark as false positive |

---

## Database Schema

| Model | Fields |
|-------|--------|
| **Project** | `id`, `name` (unique), `language`, `created_at` |
| **ErrorClassifier** | `id`, `rule_code` (unique, indexed), `type`, `priority`, `name`, `description` |
| **Run** | `id`, `project_id` (FK), `timestamp`, `commit`, `branch`, `report_file`, `status` |
| **Issue** | `id`, `run_id` (FK), `classifier_id` (FK to ErrorClassifier, nullable), `fingerprint`, `file_path`, `line`, `rule_code`, `severity`, `message`, `status` |

---

## Key Design Decisions

- **PVS-Studio JSON Report Format**: Parser supports two formats:
  - **Modern format** (current): Uses `positions[]` array with `file`, `line` fields, numeric `code` (e.g., "V501"), and numeric `level` (0-3)
  - **Legacy format**: Uses direct `fileName`, `lineNumber`, `warningCode`, and string `level`/`severity`
  - Parser automatically detects format and handles both. One warning can have multiple positions, each creating a separate issue
  - Numeric level mapping: `0` → "Analysis", `1` → "High", `2` → "Medium", `3` → "Low"
  - Warnings with empty `file` in positions are skipped (meta-warnings about analysis process)
- **Fingerprinting**: SHA-256 hash of normalized `file:line:code:message` for stable issue tracking
- **Synthetic File Paths for Analysis Warnings**: Warnings without a specific file location (e.g., V010 "Analysis of 'Utility' type projects is not supported") get a synthetic file path in the format `__analysis__/{code}` (e.g., `__analysis__/V010`). This ensures project-level warnings are tracked across runs instead of being silently discarded.
- **Error Classifier System**:
  - `Actual_warnings.csv` (416 rules) is parsed on startup via `classifier_parser.py` (handles UTF-8 BOM)
  - Each `Issue` is automatically linked to its `ErrorClassifier` by matching `rule_code` during `classify_and_store()`
  - Classifier metadata (type, priority, name) is displayed in UI with color-coded badges
  - Dashboard API returns `classifier_summary` with statistics by type and priority
- **Incremental Analysis**: Compares against the previous successful run to classify as new/existing/fixed
  - `new`: fingerprint first appears in current run → `Issue` created in current run with `status="new"`
  - `existing`: fingerprint existed in previous run → `Issue` created in current run with `status="existing"`
  - `fixed`: fingerprint disappeared from current run → **previous** run's issue gets `status="fixed"` (status is modified on the issue in the previous run, not creating a new one)
- **Dashboard Trend Chart**: Shows per-run counts ordered chronologically (oldest first):
  - `new` = count of `new` issues in this specific run
  - `fixed` = count of issues in this run that were marked as "fixed" (disappeared in the next run)
  - `total` = count of `new` + `existing` issues in this specific run
  - For the last run, `fixed` is always 0 (no next run to compare against)
  - Example: Run1 has 3 issues (V501, V824, V010), Run2 has 1 issue (V010) → Run1: {new:1, fixed:2, total:1}, Run2: {new:0, fixed:0, total:1}
- **Default Issues Filter**: The issues table defaults to showing **active** issues (`new` + `existing`) when no status filter is specified. This ensures first-time uploads display their "new" issues instead of showing "Предупреждений не найдено".
- **Dual Upload Endpoints**: 
  - `/ui/upload` — For browser-based form submission, **redirects to project dashboard** (HTTP 303) after successful upload
  - `/api/v1/upload` — For programmatic access (CI/CD, scripts), returns JSON response
  - Both endpoints share the same business logic (parse, classify, store)
  - Home page form uses `/ui/upload` to ensure proper UX flow
- **SQLite default**: Simple setup; swappable via `DATABASE_URL` env var
- **HTMX UI**: Server-rendered templates with dynamic updates, minimal custom JS
- **Dark Blue Theme**: Deep navy palette (`#0b1a2e`, `#0f2240`, `#142d50`) via CSS custom properties — not black/gray. Tables explicitly override Bootstrap's white backgrounds with `[data-theme="dark"] ... !important` selectors
- **i18n (RU/EN)**: Client-side language toggle via `I18n` module, `data-i18n`/`data-i18n-placeholder` attributes, `static/translations.json` dictionary
- **Theme persistence**: Both theme and language stored in `localStorage`, auto-detects `prefers-color-scheme`
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
- **Testing**: use `tests/conftest.py` fixtures; smoke tests in `tests/test_smoke.py`; parser tests in `tests/test_parser.py`

## Frontend Conventions

- **Theme toggling**: Use CSS custom properties on `:root` / `[data-theme="dark"]`. Dark palette is dark blue, not black
- **Dark table override**: Tables inside cards use `[data-theme="dark"] .card .table { ... !important }` to override Bootstrap's white backgrounds
- **i18n**: Use `data-i18n="key"` for text content and `data-i18n-placeholder="key"` for input placeholders. Keys live in `static/translations.json`
- **Chart.js**: Always use `createTrendChart('id', data)` from `app.js` — it handles theme-aware colors and translatable legends
- **Icons**: Use Bootstrap Icons (`bi bi-*`), not emoji, for consistency
- **JS modules**: `ThemeManager` (theme), `I18n` (language), `createTrendChart` (charts), `showToast` (notifications)
