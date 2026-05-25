# PVS-Tracker — Stack & Operations

## Modules map

| Module | Responsibility |
|--------|----------------|
| `main.py` | v1 UI/API, dashboard, platform fragments |
| `api.py` | `/api/v2` REST, profile, QG rules, warnings catalog |
| `auth_service.py` | JWT, User, RBAC |
| `incremental.py` | new / existing / fixed (per `target_platform`) |
| `platforms.py` | OS normalization, `cross_platform_fp` |
| `dashboard_context.py` | Platform metrics for dashboard |
| `notifications.py` | SMTP email on API upload |
| `webhooks.py` | `report_uploaded`, `quality_gate_evaluated` |
| `inbound_webhooks.py` | TFS/Git → Jenkins |
| `jenkins_service.py`, `project_ci.py`, `project_manage.py` | CI UI + orchestration |
| `jira_sync.py`, `jira_service.py` | Jira after upload |
| `quality_gate.py` | Rule-code gate evaluation after upload |
| `git_integration.py` | Clone/cache for code viewer |

## Preferred stack

| Area | Choice |
|------|--------|
| Python | >= 3.10 |
| Web | fastapi >= 0.110 |
| ORM | sqlmodel >= 0.0.14 |
| Auth API | PyJWT, bcrypt |
| UI | htmx, bootstrap 5, chart.js |
| DB dev | sqlite |
| DB prod | postgresql |

**Banned:** celery, rq, redis, kafka, docker (v1 policy).

## Environment variables

From `.env.example` + code:

| Variable | Module |
|----------|--------|
| `DATABASE_URL` | `db.py` |
| `SECRET_KEY` | `main.py` sessions |
| `JWT_SECRET_KEY` | `auth_service.py` |
| `WEBHOOK_URL`, `WEBHOOK_SECRET` | `webhooks.py` |
| `WEBHOOK_USERNAME`, `WEBHOOK_PASSWORD` | `inbound_webhooks.py` |
| `JENKINS_URL`, `JENKINS_JOB_NAME`, … | `jenkins_service.py` |
| `JIRA_URL`, `JIRA_*` | `jira_service.py` |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_USE_TLS`, `APP_BASE_URL` | `notifications.py` |
| `GIT_CACHE_DIR`, `SNAPSHOTS_DIR`, `GIT_CACHE_TTL_MINUTES`, `GIT_TIMEOUT_SECONDS` | `git_integration.py` |

`JWT_ALGORITHM` / `ACCESS_TOKEN_EXPIRE_MINUTES` in `.env.example` — token TTL hardcoded 24h in `auth_service.py` unless code updated.

## Deployment

```ini
ExecStart=.../uvicorn pvs_tracker.main:app --host 0.0.0.0 --port 8080
EnvironmentFile=/opt/pvs-tracker/.env
WorkingDirectory=/opt/pvs-tracker
```

Windows: NSSM / WinSW with same module path.

Unit files are **not** shipped in repo — examples only in `spec.md` §8.

## PVS report

```bash
pvs-studio-analyzer analyze --outputFormat=json
```

## References

| Topic | File |
|-------|------|
| Spec | `.cursor/spec.md` |
| Rules | `.cursor/rules.md` |
| Context | `.cursor/context.md` |
| User README | `README.md` |
