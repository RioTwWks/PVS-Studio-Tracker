---
name: add-api-route
description: >-
  Adds FastAPI routes to PVS-Studio Tracker (api.py v2 REST or main.py v1).
  Use when adding API endpoints, Pydantic schemas, JWT auth, project RBAC,
  or curl test instructions for new routes.
---

# Add API Route

Parent: [pvs-tracker-dev](../pvs-tracker-dev/SKILL.md). Contracts: [.cursor/spec.md](../../spec.md), [.cursor/rules.md](../../rules.md).

## Choose surface

| Need | File | Prefix | Response |
|------|------|--------|----------|
| REST, RBAC, CI/automation | `pvs_tracker/api.py` | `/api/v2` | JSON only |
| Legacy upload/dashboard/ignore | `pvs_tracker/main.py` | `/api/v1` or `/ui/*` | JSON or HTML |
| Code viewer files | `pvs_tracker/code_viewer.py` | `/ui/file`, … | HTML partial |

Router v2 is mounted in `main.py`: `app.include_router(api_v2_router)`.

## API v2 workflow

```
Task Progress:
- [ ] Add Pydantic models in api.py (schemas section)
- [ ] Add @router.METHOD("/path") handler
- [ ] Auth: Depends(require_auth) or require_admin / require_role(...)
- [ ] Project scope: can_access_project / can_modify_project
- [ ] DB: follow existing api.py session pattern
- [ ] Optional: log_activity(...) for mutations
- [ ] Document curl + expected status/body
```

## Auth (`auth_service.py`)

- `Depends(require_auth)` → `User` (JWT Bearer **or** UI session if username exists in DB).
- `Depends(require_admin)` — global admin only.
- `require_role(UserRole.USER)` — role hierarchy VIEWER < USER < ADMIN.

Project checks:

```python
if not can_access_project(user, project_id):
    raise HTTPException(status_code=403, detail="Access denied")
if not can_modify_project(user, project_id):
    raise HTTPException(status_code=403, detail="Insufficient permissions")
```

## Pydantic v2 pattern

```python
class MyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    optional_field: Optional[str] = None
```

Place new schemas near existing ones in `api.py` (after imports, before routes).

## Handler pattern (match `api.py` style)

```python
@router.post("/projects/{project_id}/things")
async def create_thing(
    project_id: int,
    body: MyCreate,
    user: User = Depends(require_auth),
    session: Session = Depends(lambda: None),
):
    from sqlmodel import Session
    from pvs_tracker.db import engine
    with Session(engine) as db_session:
        if not can_modify_project(user, project_id):
            raise HTTPException(status_code=403, detail="Access denied")
        # ... business logic ...
        db_session.commit()
        return {"id": thing.id}
```

Prefer `HTTPException(404|400|403)` with clear `detail`. Use `logger` if adding logging.

## v1 (`main.py`) pattern

```python
@app.post("/api/v1/...")
async def my_endpoint(
    ...,
    session: Session = Depends(get_session),
    _user: str = Depends(require_auth),  # session username string
):
    ...
    return {"status": "ok"}
```

- UI routes: `HTMLResponse` / `RedirectResponse`, not JSON.
- Do not break existing upload/dashboard paths.

## Do not

- Return HTML from `/api/v2/*` or `/api/v1/*`.
- Skip project RBAC on project-scoped v2 routes.
- Add routes outside `api.py` for v2 (keeps prefix `/api/v2`).

## Verification

```bash
# Login (v2)
curl -s -X POST http://localhost:8080/api/v2/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin"}'

# Call new endpoint (replace TOKEN and path)
curl -s -w "\n%{http_code}" http://localhost:8080/api/v2/... \
  -H "Authorization: Bearer TOKEN"
```

Add or extend tests in `tests/test_smoke.py` or a dedicated test module if behavior is non-trivial.

End with:

```text
✅ Файл готов. Запусти: curl ... (команда выше)
Ожидаемый результат: HTTP <код>, тело <кратко>.
```
