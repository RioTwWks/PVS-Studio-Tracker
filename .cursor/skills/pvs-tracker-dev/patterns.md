# PVS-Tracker — Code Patterns

## Typing & errors

- Strict annotations; avoid implicit `Any`.
- API: `HTTPException`.
- UI upload failure: redirect or HTML error (not JSON).
- Background: `logger.error(...)`.

## Config

No `config.py`. Read env in the module that uses it:

```python
import os
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./pvs_tracker.db")
```

## Database

- `Depends(get_session)` in routes.
- One `session.commit()` after full incremental diff.
- Ignore: update `Issue.status`, not a separate ignore table.

## New API route

| Target | File | Auth |
|--------|------|------|
| UI / v1 JSON | `main.py` | `require_auth` or open (document choice) |
| REST v2 | `api.py` | `Depends(get_current_user)` from `auth_service` |

Return JSON only under `/api/*`.

## Parser

- Empty file → `__analysis__/{code}`
- `.get()` with defaults; log unknown keys

## HTMX

- Target `#issues-table-full` for filter form
- CI panel: `#project-ci-panel`, `innerHTML` swap; toast via hidden `#ci-toast-payload` in response
- Thread all filter query params through sort + pagination URLs
- Partials: no `base.html`
- `project_manage` templates must pass `current_user` in context (`_template_ctx`)

## Toast (CI toggles)

- Use `sq-toast` only — Bootstrap `.toast:not(.show) { display: none }`
- After CI POST: parse `xhr.responseText` for `#ci-toast-payload` or `HX-Trigger` JSON

## Inline code (Issues)

- `toggleInlineCode` in `app.js`; row class `is-open`; close animation `sq-codeHide`

## Testing

```bash
pytest tests/test_parser.py -v
pytest tests/test_smoke.py -v
pytest tests/test_profile_notifications.py -v
pytest tests/test_platforms.py -v
pytest tests/test_classifier.py tests/test_code_viewer.py -v
```

Mocks: `ldap3`, `BackgroundTasks` / asyncio tasks as needed.

## Async

- `async def` routes
- `httpx` for webhooks
- Sync SQLModel session in dependencies

## Error classifier

Startup load `Actual_warnings.csv` → link `classifier_id` in `incremental.py`.
