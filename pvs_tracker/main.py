import asyncio
import contextlib
import os
from contextlib import asynccontextmanager
from datetime import datetime
from urllib.parse import quote

from fastapi import Depends, FastAPI, Form, HTTPException, Request, UploadFile, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from typing import Optional
from starlette.middleware.sessions import SessionMiddleware
from sqlmodel import Session, select, func

from pvs_tracker.models import (
    ActivityLog,
    Issue,
    IssueComment,
    MetricSnapshot,
    Project,
    ProjectMember,
    Run,
    RunReport,
    SQLModel,
    CodeSnapshotFile,
    ErrorClassifier,
    User,
    UserRole,
    GlobalSettings,
    QualityGate,
    RestQueueJob,
)
from pvs_tracker.parser import parse_pvs_report_bytes
from pvs_tracker.artifact_storage import store_code_snapshot, store_run_report
from pvs_tracker.upload_metadata import merge_commit_upload_fields, parse_commit_metadata_bytes
from pvs_tracker.incremental import classify_and_store
from pvs_tracker.classifier_parser import parse_classifier_csv
from pvs_tracker.db import engine, get_session
import pvs_tracker.code_viewer as code_viewer_module
from pvs_tracker.code_viewer import merge_code_snapshot, router as code_viewer_router
from pvs_tracker.api import router as api_v2_router
from pvs_tracker.quality_gate import create_default_quality_gate, evaluate_quality_gate
from pvs_tracker.security import hash_password
from pvs_tracker.startup_state import mark_startup_finished, startup_initialization_complete
from pvs_tracker.auth_service import (
    authenticate_credentials,
    clear_session,
    establish_session,
    get_current_user as get_current_user_model,
    require_admin,
    require_auth,
)

# ---------------------------------------------------------------------------
# App & DB
# ---------------------------------------------------------------------------

import logging as _logging

_logging.getLogger("spnego").setLevel(_logging.WARNING)
_logging.getLogger("spnego._gss").setLevel(_logging.WARNING)

logger = _logging.getLogger(__name__)


def _run_startup_init() -> None:
    """DB migrations and seed data — runs in lifespan or sync import (Windows Docker)."""
    logger.info("Startup: applying database migrations and default data")
    _migrate_database()
    _initialize_default_data()
    with Session(engine) as session:
        _sync_project_groups(session)
    with Session(engine) as lang_session:
        from pvs_tracker.warnings_catalog import backfill_classifier_languages

        backfill_classifier_languages(lang_session)
    logger.info("Startup: database initialization complete")


def _eager_startup_init_if_requested() -> None:
    """Sync DB init at import — Windows Docker containers hang in asyncio.to_thread."""
    if os.getenv("PVS_SYNC_STARTUP_INIT", "").lower() not in ("1", "true", "yes"):
        return
    if startup_initialization_complete():
        return
    logger.info("Startup: synchronous initialization (PVS_SYNC_STARTUP_INIT)")
    try:
        _run_startup_init()
        mark_startup_finished(None)
    except BaseException as exc:
        mark_startup_finished(exc)
        raise


_eager_startup_init_if_requested()


@asynccontextmanager
async def _app_lifespan(_app: FastAPI):
    from pvs_tracker.rest_queue.runtime import start_embedded_workers, stop_embedded_workers

    async def _init_background() -> None:
        error: BaseException | None = None
        try:
            if startup_initialization_complete():
                logger.info("Startup: database already initialized")
                start_embedded_workers()
                return
            timeout = float(os.getenv("DB_STARTUP_TIMEOUT", "120"))
            await asyncio.wait_for(asyncio.to_thread(_run_startup_init), timeout=timeout)
            start_embedded_workers()
        except asyncio.TimeoutError:
            error = TimeoutError(f"Database startup exceeded {timeout}s")
            logger.error("Startup initialization timed out after %ss", timeout)
        except BaseException as exc:
            error = exc
            logger.exception("Startup initialization failed")
        finally:
            if not startup_initialization_complete():
                mark_startup_finished(error)

    init_task = asyncio.create_task(_init_background())

    yield

    init_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await init_task
    stop_embedded_workers()


app = FastAPI(title="PVS-Studio Tracker", lifespan=_app_lifespan)
_session_https = os.getenv("SESSION_HTTPS_ONLY", "false").lower() in ("1", "true", "yes")
_session_same_site = os.getenv("SESSION_SAME_SITE", "lax")
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SECRET_KEY", "dev-change-me"),
    https_only=_session_https,
    same_site=_session_same_site,
)

BASE_DIR = os.path.dirname(__file__)


def _optional_form(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _run_commit_fields(
    commit: Optional[str],
    commit_author_name: Optional[str],
    commit_author_email: Optional[str],
    release_version: Optional[str] = None,
) -> dict[str, Optional[str]]:
    return {
        "commit": _optional_form(commit),
        "commit_author_name": _optional_form(commit_author_name),
        "commit_author_email": _optional_form(commit_author_email),
        "release_version": _optional_form(release_version),
    }


def _apply_run_commit_fields(
    run: Run,
    *,
    commit: Optional[str] = None,
    commit_author_name: Optional[str] = None,
    commit_author_email: Optional[str] = None,
    release_version: Optional[str] = None,
) -> None:
    """Update run commit/author/version when re-uploading to an existing run."""
    fields = _run_commit_fields(
        commit, commit_author_name, commit_author_email, release_version
    )
    if fields["commit"] is not None:
        run.commit = fields["commit"]
    if fields["commit_author_name"] is not None:
        run.commit_author_name = fields["commit_author_name"]
    if fields["commit_author_email"] is not None:
        run.commit_author_email = fields["commit_author_email"]
    if fields["release_version"] is not None:
        run.release_version = fields["release_version"]


def _sync_project_release_version(project: Project, release_version: Optional[str]) -> None:
    """Keep Project.release_version in sync with the latest uploaded run version."""
    if release_version:
        project.release_version = release_version


def _migrate_database() -> None:
    """Apply schema migrations for existing databases."""
    # Create all tables (safe if they already exist)
    SQLModel.metadata.create_all(engine)
    from pvs_tracker.db_migrate_ci import apply_ci_schema_migration

    apply_ci_schema_migration()

    with Session(engine) as session:
        # Check if migration is needed
        try:
            projects = session.exec(select(Project).limit(1)).all()
            if projects and hasattr(projects[0], "source_root_win"):
                # Already migrated
                pass
        except Exception:
            pass

        # Execute raw SQL to add new columns (SQLite)
        from sqlalchemy import text

        try:
            with engine.connect() as conn:
                # Add source_root_win
                try:
                    conn.execute(
                        text(
                            "ALTER TABLE project ADD COLUMN source_root_win VARCHAR"
                        )
                    )
                    conn.commit()
                except Exception:
                    pass  # Column may already exist

                # Add source_root_linux
                try:
                    conn.execute(
                        text(
                            "ALTER TABLE project ADD COLUMN source_root_linux VARCHAR"
                        )
                    )
                    conn.commit()
                except Exception:
                    pass  # Column may already exist

                # Add quality_gate_id
                try:
                    conn.execute(
                        text(
                            "ALTER TABLE project ADD COLUMN quality_gate_id INTEGER"
                        )
                    )
                    conn.commit()
                except Exception:
                    pass  # Column may already exist

                # Add description
                try:
                    conn.execute(
                        text(
                            "ALTER TABLE project ADD COLUMN description VARCHAR"
                        )
                    )
                    conn.commit()
                except Exception:
                    pass  # Column may already exist

                for col_sql in (
                    "ALTER TABLE user ADD COLUMN first_name VARCHAR",
                    "ALTER TABLE user ADD COLUMN last_name VARCHAR",
                    "ALTER TABLE user ADD COLUMN notify_api_uploads BOOLEAN DEFAULT 0",
                    "ALTER TABLE project ADD COLUMN source_root_macos VARCHAR",
                    "ALTER TABLE run ADD COLUMN target_platform VARCHAR DEFAULT 'windows'",
                    "ALTER TABLE issue ADD COLUMN cross_platform_fp VARCHAR",
                    "ALTER TABLE globalsettings ADD COLUMN default_source_root_macos VARCHAR",
                    "ALTER TABLE errorclassifier ADD COLUMN category VARCHAR",
                    "ALTER TABLE errorclassifier ADD COLUMN language VARCHAR",
                    "ALTER TABLE errorclassifier ADD COLUMN doc_url VARCHAR",
                    "ALTER TABLE errorclassifier ADD COLUMN synced_at DATETIME",
                    "ALTER TABLE run ADD COLUMN commit_author_name VARCHAR",
                    "ALTER TABLE run ADD COLUMN commit_author_email VARCHAR",
                    "ALTER TABLE run ADD COLUMN release_version VARCHAR DEFAULT ''",
                    "ALTER TABLE run ADD COLUMN report_type VARCHAR DEFAULT 'incremental'",
                    "ALTER TABLE issue ADD COLUMN author_name VARCHAR",
                    "ALTER TABLE issue ADD COLUMN author_email VARCHAR",
                    "ALTER TABLE user ADD COLUMN display_name VARCHAR",
                    "ALTER TABLE user ADD COLUMN auth_provider VARCHAR DEFAULT 'local'",
                ):
                    try:
                        conn.execute(text(col_sql))
                        conn.commit()
                    except Exception:
                        pass

                try:
                    with engine.connect() as conn:
                        # Проверяем, есть ли у колонки password_hash ограничение NOT NULL
                        res = conn.exec_driver_sql("PRAGMA table_info(user)").fetchall()
                        for col in res:
                            if col[1] == "password_hash" and col[3] == 1:  # notnull = 1
                                # Создаём временную таблицу без NOT NULL
                                conn.exec_driver_sql("BEGIN TRANSACTION")
                                # Скопируем структуру
                                conn.exec_driver_sql("CREATE TABLE user_new (id INTEGER PRIMARY KEY, username VARCHAR NOT NULL, first_name VARCHAR, last_name VARCHAR, display_name VARCHAR, email VARCHAR, notify_api_uploads BOOLEAN, password_hash VARCHAR, auth_provider VARCHAR, role VARCHAR, is_active BOOLEAN, created_at DATETIME, last_login DATETIME)")
                                # Скопируем данные
                                conn.exec_driver_sql("INSERT INTO user_new SELECT id, username, first_name, last_name, display_name, email, notify_api_uploads, password_hash, auth_provider, role, is_active, created_at, last_login FROM user")
                                # Удалим старую таблицу
                                conn.exec_driver_sql("DROP TABLE user")
                                # Переименуем новую
                                conn.exec_driver_sql("ALTER TABLE user_new RENAME TO user")
                                # Пересоздадим индексы и триггеры (если есть)
                                conn.exec_driver_sql("CREATE INDEX ix_user_username ON user (username)")
                                conn.exec_driver_sql("CREATE INDEX ix_user_auth_provider ON user (auth_provider)")
                                conn.exec_driver_sql("COMMIT")
                                break
                except Exception as e:
                    _logging.warning("Failed to remove NOT NULL from password_hash: %s", e)

                # === Создание таблицы ProjectGroup и заполнение начальными данными ===
                try:
                    with engine.connect() as conn:
                        # Проверяем существование таблицы
                        res = conn.exec_driver_sql(
                            "SELECT name FROM sqlite_master WHERE type='table' AND name='projectgroup'"
                        ).fetchone()
                        if not res:
                            # Создаём таблицу
                            conn.exec_driver_sql("""
                                CREATE TABLE projectgroup (
                                    id INTEGER PRIMARY KEY,
                                    name VARCHAR(100) NOT NULL UNIQUE,
                                    display_order INTEGER NOT NULL DEFAULT 0,
                                    created_at DATETIME NOT NULL
                                )
                            """)
                            # Индекс
                            conn.exec_driver_sql("CREATE INDEX ix_projectgroup_name ON projectgroup (name)")
                            conn.commit()

                            # Заполняем уникальными значениями group_name из существующих проектов
                            existing_groups = conn.exec_driver_sql(
                                "SELECT DISTINCT group_name FROM project WHERE group_name IS NOT NULL AND group_name != ''"
                            ).fetchall()
                            group_names = {row[0] for row in existing_groups}
                            # Добавляем стандартные группы, если их нет
                            default_groups = ["QA", "QD", "QF", "QG", "QS", "QW", "Other_Projects", "Ungrouped"]
                            for gn in sorted(set(default_groups) | group_names):
                                order = default_groups.index(gn) if gn in default_groups else 999
                                conn.exec_driver_sql(
                                    "INSERT INTO projectgroup (name, display_order, created_at) VALUES (?, ?, ?)",
                                    (gn, order, datetime.utcnow())
                                )
                            conn.commit()
                except Exception as e:
                    _logging.warning("ProjectGroup migration failed: %s", e)

        except Exception:
            pass  # Migration failed, continue anyway

        _backfill_cross_platform_fps(session)
        _backfill_issue_authors(session)


def _backfill_issue_authors(session: Session) -> None:
    """Backfill issue author_name/email for legacy rows with missing data.

    Rules (SonarQube-like):
    - new: author is current run commit author
    - existing/fixed: author is previous run issue author (same fingerprint), otherwise fallback to current run author
    - first run (no prev): fallback to current run author
    """
    runs = session.exec(
        select(Run).where(Run.status == "done").order_by(Run.timestamp.asc())
    ).all()

    # (project_id, target_platform) -> last done run
    last_done: dict[tuple[int, str], Run] = {}

    for run in runs:
        key = (run.project_id, run.target_platform or "windows")
        prev_run = last_done.get(key)

        prev_issue_author: dict[str, tuple[Optional[str], Optional[str]]] = {}
        if prev_run:
            prev_issues = session.exec(
                select(Issue).where(Issue.run_id == prev_run.id)
            ).all()
            for pi in prev_issues:
                if pi.fingerprint:
                    prev_issue_author[pi.fingerprint] = (pi.author_name, pi.author_email)

        issues = session.exec(select(Issue).where(Issue.run_id == run.id)).all()
        for issue in issues:
            # Fill only when both are missing.
            if issue.author_name is not None and issue.author_email is not None:
                continue

            source_name: Optional[str] = None
            source_email: Optional[str] = None

            if issue.status == "new" or prev_run is None:
                source_name = run.commit_author_name
                source_email = run.commit_author_email
            else:
                prev = prev_issue_author.get(issue.fingerprint or "")
                if prev and (prev[0] is not None or prev[1] is not None):
                    source_name, source_email = prev
                else:
                    source_name = run.commit_author_name
                    source_email = run.commit_author_email

            if source_name is not None and issue.author_name is None:
                issue.author_name = source_name
            if source_email is not None and issue.author_email is None:
                issue.author_email = source_email

            session.add(issue)

        last_done[key] = run

    session.commit()


def _backfill_cross_platform_fps(session: Session) -> None:
    """Fill cross_platform_fp for legacy issues after schema migration."""
    from pvs_tracker.platforms import compute_cross_platform_fp

    missing = session.exec(
        select(Issue).where(Issue.cross_platform_fp == None)  # noqa: E711
    ).all()
    if not missing:
        return

    global_settings = session.exec(select(GlobalSettings).where(GlobalSettings.id == 1)).first()
    updated = 0
    for issue in missing:
        run = session.get(Run, issue.run_id)
        if not run:
            continue
        project = session.get(Project, run.project_id)
        if not project:
            continue
        platform = run.target_platform or "windows"
        issue.cross_platform_fp = compute_cross_platform_fp(
            issue.file_path,
            issue.rule_code,
            issue.message,
            project=project,
            global_settings=global_settings,
            platform=platform,  # type: ignore[arg-type]
        )
        session.add(issue)
        updated += 1
    if updated:
        session.commit()


def _initialize_default_data() -> None:
    """Initialize default quality gates and admin user if they don't exist."""
    with Session(engine) as session:
        _load_error_classifiers(session)
        create_default_quality_gate(session)

        # Create default admin user if no users exist
        existing_user = session.exec(select(User).limit(1)).first()
        if not existing_user:
            admin_user = User(
                username="admin",
                email="admin@localhost",
                password_hash=hash_password("admin"),
                auth_provider="local",
                role=UserRole.ADMIN,
                is_active=True,
            )
            session.add(admin_user)
            session.commit()


def _sync_project_groups(session: Session) -> None:
    from pvs_tracker.models import ProjectGroup
    # Все уникальные имена групп из проектов
    project_groups = session.exec(select(Project.group_name).distinct()).all()
    group_names = {gn for gn in project_groups if gn and gn.strip()}
    # Стандартные группы (должны быть)
    default_groups = ["QA", "QD", "QF", "QG", "QS", "QW", "Other_Projects", "Ungrouped"]
    group_names.update(default_groups)
    
    # Существующие группы в БД
    existing = {g.name for g in session.exec(select(ProjectGroup)).all()}
    
    # Добавляем недостающие
    for name in group_names:
        if name not in existing:
            order = default_groups.index(name) if name in default_groups else 999
            session.add(ProjectGroup(name=name, display_order=order))
    session.commit()


def _load_error_classifiers(session: Session) -> None:
    """Load error classifier data from Actual_warnings.csv if not already present."""
    # Check if classifiers are already loaded
    existing = session.exec(select(ErrorClassifier).limit(1)).first()
    if existing:
        return

    # Try to load from CSV
    csv_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "Actual_warnings.csv")
    if not os.path.exists(csv_path):
        return

    from pvs_tracker.warnings_catalog import backfill_classifier_languages, resolve_warning_language

    classifiers = parse_classifier_csv(csv_path)
    for clf in classifiers:
        clf["language"] = resolve_warning_language(
            clf["rule_code"],
            clf.get("category"),
            clf.get("language"),
        )
        session.add(ErrorClassifier(**clf))
    session.commit()
    backfill_classifier_languages(session)


# Templates
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
from pvs_tracker.project_urls import project_ui_path, register_project_url_globals
from pvs_tracker.template_helpers import software_quality_label
from pvs_tracker.rule_documentation import (
    build_classifier_maps,
    fetch_rule_documentation,
    resolve_issue_classifier,
    rule_documentation_url,
)

register_project_url_globals(templates.env)
templates.env.globals["software_quality_label"] = software_quality_label
templates.env.globals["resolve_issue_classifier"] = resolve_issue_classifier

# Register code_viewer router and pass templates reference
code_viewer_module.templates = templates
app.include_router(code_viewer_router)

# Register API v2 router (SonarQube-like features)
app.include_router(api_v2_router)

from pvs_tracker.health import router as health_router
from pvs_tracker.inbound_webhooks import router as inbound_webhooks_router
from pvs_tracker.project_manage import router as project_manage_router

app.include_router(health_router)
app.include_router(inbound_webhooks_router)
app.include_router(project_manage_router)

# Static files
STATIC_DIR = os.path.join(os.path.dirname(BASE_DIR), "static")
if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# ---------------------------------------------------------------------------
# Dependencies — get_session from pvs_tracker.db
# ---------------------------------------------------------------------------


def _ui_current_user(request: Request) -> User | None:
    """Current User for Jinja templates (session or JWT)."""
    return get_current_user_model(request, None)


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html")


@app.post("/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    if not username.strip() or not password:
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Username and password are required"},
        )
    with Session(engine) as session:
        user = authenticate_credentials(session, username, password)
    if not user:
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Invalid username or password"},
        )
    establish_session(request, user)
    return RedirectResponse(url="/", status_code=303)


@app.get("/logout")
async def logout(request: Request):
    clear_session(request)
    return RedirectResponse(url="/", status_code=303)


# ---------------------------------------------------------------------------
# UI routes
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def home(request: Request, session: Session = Depends(get_session)):
    from pvs_tracker.project_ci import list_ci_projects_grouped

    projects_by_group = list_ci_projects_grouped(session)
    return templates.TemplateResponse(
        request,
        "home.html",
        {
            "current_user": _ui_current_user(request),
            "projects_by_group": projects_by_group,
        },
    )


@app.post("/ui/projects", response_class=HTMLResponse)
async def create_project_ui(
    request: Request,
    project_name: str = Form(...),
    branch: str = Form("main"),
    language: str = Form("c++"),
    target_platform: str = Form("windows"),
    file: UploadFile = Form(None),
    code_snapshot: UploadFile = Form(None),
    commit_metadata: UploadFile = Form(None),
    commit: str = Form(None),
    session: Session = Depends(get_session),
    _user: str = Depends(require_auth),
):
    """Create a project from the web UI, optionally with an initial report."""
    from pvs_tracker.platforms import normalize_target_platform

    platform = normalize_target_platform(target_platform)
    name = project_name.strip()
    if not name:
        from pvs_tracker.project_ci import list_ci_projects_grouped

        return templates.TemplateResponse(
            request,
            "home.html",
            {
                "current_user": _ui_current_user(request),
                "projects_by_group": list_ci_projects_grouped(session),
                "error": "Project name is required",
            },
            status_code=400,
        )

    project = session.exec(select(Project).where(Project.name == name)).first()
    if project:
        if file and file.filename:
            return await upload_report_ui(
                request=request,
                project_name=name,
                file=file,
                source_archive=None,
                code_snapshot=code_snapshot,
                commit_metadata=commit_metadata,
                commit=commit,
                commit_author_name=None,
                commit_author_email=None,
                release_version=None,
                branch=(branch or project.git_branch or "main").strip() or "main",
                target_platform=platform,
                session=session,
                _user=_user,
            )
        from pvs_tracker.project_ci import ensure_project_slug

        ensure_project_slug(session, project)
        return RedirectResponse(
            url=project_ui_path(project, "dashboard", platform_filter=platform),
            status_code=303,
        )

    default_branch = (branch or "main").strip() or "main"
    project = Project(name=name, language=language or "c++", git_branch=default_branch)
    session.add(project)
    session.commit()
    session.refresh(project)
    from pvs_tracker.project_ci import ensure_project_slug

    ensure_project_slug(session, project)

    if file and file.filename:
        return await upload_report_ui(
            request=request,
            project_name=name,
            file=file,
            source_archive=None,
            code_snapshot=code_snapshot,
            commit_metadata=commit_metadata,
            commit=commit,
            commit_author_name=None,
            commit_author_email=None,
            release_version=None,
            branch=default_branch,
            target_platform=platform,
            session=session,
            _user=_user,
        )

    return RedirectResponse(
        url=project_ui_path(project, "dashboard", platform_filter=platform),
        status_code=303,
    )


@app.get("/ui/projects/{project_key}/dashboard", response_class=HTMLResponse)
async def ui_dashboard(
    project_key: str,
    request: Request,
    branch: str = "",
    platform_filter: str = "windows",
    upload_error: str = "",
    tab: str = "",
    settings_tab: str = "",
    ci_error: str = "",
    session: Session = Depends(get_session),
):
    from pvs_tracker.project_urls import require_project_by_key

    project = require_project_by_key(session, project_key)
    project_id = project.id

    from pvs_tracker.dashboard_context import (
        list_project_branches,
        resolve_active_branch,
        sync_project_branch,
    )

    all_runs = session.exec(
        select(Run)
        .where(Run.project_id == project_id, Run.status == "done")
        .order_by(Run.timestamp.desc()),
    ).all()

    branches = list_project_branches(project, all_runs)
    active_branch = resolve_active_branch(project, all_runs, branch)
    if active_branch:
        sync_project_branch(session, project, active_branch)
        if active_branch not in branches:
            branches.append(active_branch)

    from pvs_tracker.dashboard_context import (
        build_platform_metrics,
        build_quality_gate_result,
    )
    from pvs_tracker.platforms import normalize_platform_filter

    pf = normalize_platform_filter(platform_filter)
    metrics = build_platform_metrics(session, project_id, active_branch, pf)
    history = metrics["history"]
    history_by_platform = metrics["history_by_platform"]
    issues_total = metrics["issues_total"]

    qg_result = build_quality_gate_result(
        session, project_id, active_branch, pf, history
    )

    quality_gates = session.exec(select(QualityGate).order_by(QualityGate.name)).all()

    from pvs_tracker.admin_utils import is_admin
    from pvs_tracker.project_form_context import project_form_context
    from pvs_tracker.project_groups import get_group_choices, get_group_id_by_name

    form_ctx = project_form_context(project, edit=True, edit_id=project.id, load_jira=False)
    form_ctx["group_choices"] = get_group_choices(session)
    form_ctx["group_id"] = get_group_id_by_name(session, project.group_name or "Ungrouped")
    form_ctx["is_admin"] = is_admin(request)
    sub = (settings_tab or "params").strip().lower()
    if sub not in ("params", "sources", "quality"):
        sub = "params"
    err = ci_error.strip()
    form_ctx["flash_message"] = err or None
    form_ctx["flash_is_error"] = bool(err)
    form_ctx["show_branch_field"] = False
    form_ctx["active_branch"] = active_branch

    from pvs_tracker.ci_activity_log import fetch_ci_activity_logs

    form_ctx["ci_activity_logs"] = fetch_ci_activity_logs(session, project_id)

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "current_user": _ui_current_user(request),
            "project": project,
            "history": history,
            "history_by_platform": history_by_platform,
            "branches": branches,
            "active_branch": active_branch,
            "platform_filter": pf,
            "issues_total": issues_total,
            "qg_result": qg_result,
            "quality_gates": quality_gates,
            "upload_error": upload_error.strip() or None,
            "initial_tab": tab.strip() or "overview",
            "initial_settings_subtab": sub,
            **form_ctx,
        },
    )


@app.get("/api/v1/projects/{project_id}/platform-metrics")
def api_platform_metrics(
    project_id: int,
    branch: str = "",
    platform_filter: str = "windows",
    session: Session = Depends(get_session),
):
    """JSON metrics for in-page OS platform switching."""
    from pvs_tracker.dashboard_context import build_platform_metrics, resolve_active_branch

    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    all_runs = session.exec(
        select(Run)
        .where(Run.project_id == project_id, Run.status == "done")
        .order_by(Run.timestamp.desc()),
    ).all()
    active_branch = resolve_active_branch(project, all_runs, branch)
    return build_platform_metrics(session, project_id, active_branch, platform_filter)


@app.get("/ui/projects/{project_key}/overview-fragment", response_class=HTMLResponse)
async def ui_overview_fragment(
    project_key: str,
    request: Request,
    branch: str = "",
    platform_filter: str = "windows",
    session: Session = Depends(get_session),
):
    """HTML fragment: overview KPI for selected platform filter."""
    from pvs_tracker.dashboard_context import (
        build_platform_metrics,
        build_quality_gate_result,
        resolve_active_branch,
    )
    from pvs_tracker.platforms import normalize_platform_filter
    from pvs_tracker.project_urls import require_project_by_key

    project = require_project_by_key(session, project_key)
    project_id = project.id

    all_runs = session.exec(
        select(Run)
        .where(Run.project_id == project_id, Run.status == "done")
        .order_by(Run.timestamp.desc()),
    ).all()
    active_branch = resolve_active_branch(project, all_runs, branch)
    pf = normalize_platform_filter(platform_filter)
    metrics = build_platform_metrics(session, project_id, active_branch, pf)
    qg_result = build_quality_gate_result(
        session, project_id, active_branch, pf, metrics["history"]
    )

    return templates.TemplateResponse(
        request,
        "dashboard/_overview_content.html",
        {
            "history": metrics["history"],
            "qg_result": qg_result,
            "platform_filter": pf,
        },
    )


@app.get("/ui/projects/{project_key}/trends-fragment", response_class=HTMLResponse)
async def ui_trends_fragment(
    project_key: str,
    request: Request,
    branch: str = "",
    platform_filter: str = "windows",
    session: Session = Depends(get_session),
):
    """HTMX/HTML fragment: trends KPI + chart area for selected platform."""
    from pvs_tracker.dashboard_context import build_platform_metrics, resolve_active_branch
    from pvs_tracker.platforms import normalize_platform_filter
    from pvs_tracker.project_urls import require_project_by_key

    project = require_project_by_key(session, project_key)
    project_id = project.id

    all_runs = session.exec(
        select(Run)
        .where(Run.project_id == project_id, Run.status == "done")
        .order_by(Run.timestamp.desc()),
    ).all()
    active_branch = resolve_active_branch(project, all_runs, branch)
    pf = normalize_platform_filter(platform_filter)
    metrics = build_platform_metrics(session, project_id, active_branch, pf)

    return templates.TemplateResponse(
        request,
        "dashboard/_trends_content.html",
        {
            "history": metrics["history"],
            "history_by_platform": metrics["history_by_platform"],
            "platform_filter": pf,
        },
    )


def _issues_display_paths(
    session: Session,
    project: Project,
    issues: list[Issue],
    issue_platforms: dict[int, str],
    platform_filter: str,
) -> dict[int, str]:
    from pvs_tracker.file_resolver import get_effective_source_root, normalize_file_path_for_display
    from pvs_tracker.platforms import PLATFORMS

    global_settings = session.exec(select(GlobalSettings).where(GlobalSettings.id == 1)).first()
    display_paths: dict[int, str] = {}
    for issue in issues:
        plat = issue_platforms.get(issue.id)
        if not plat:
            plat = platform_filter if platform_filter in PLATFORMS else "windows"
        effective_root = get_effective_source_root(
            project.source_root_win,
            project.source_root_linux,
            global_settings,
            project.source_root_macos,
            platform=plat,
        )
        display_paths[issue.id] = normalize_file_path_for_display(issue.file_path, effective_root)
    return display_paths


@app.get("/ui/issues", response_class=HTMLResponse)
async def ui_issues(
    request: Request,
    project_id: int,
    branch: str = "",
    platform_filter: str = "windows",
    severity: str = "",
    status_filter: str = "",
    type_filter: str = "",
    priority_filter: str = "",
    q: str = "",
    page: int = 1,
    sort_by: str = "file",
    order: str = "asc",
    fragment: bool = False,
    session: Session = Depends(get_session),
):
    from pvs_tracker.issues_query import (
        compute_issue_facets,
        compute_total_effort,
        format_relative_time,
        group_issues_by_file,
        resolve_issues_for_filter,
    )
    from pvs_tracker.platforms import normalize_platform_filter

    pf = normalize_platform_filter(platform_filter)
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    classifiers = session.exec(select(ErrorClassifier)).all()
    classifier_map, classifier_by_code = build_classifier_maps(classifiers)

    base_vars = {
        "current_user": _ui_current_user(request),
        "project_id": project_id,
        "branch": branch,
        "platform_filter": pf,
        "severity": severity,
        "status_filter": status_filter,
        "type_filter": type_filter,
        "priority_filter": priority_filter,
        "q": q,
        "classifier_map": classifier_map,
        "classifier_by_code": classifier_by_code,
        "sort_by": sort_by,
        "order": order,
        "page": page,
    }

    all_for_facets, run_id, issue_platforms, issue_run_ids, show_platform = (
        resolve_issues_for_filter(
            session,
            project,
            branch,
            pf,
            q=q,
            sort_by=sort_by,
            order=order,
            classifier_map=classifier_map,
        )
    )

    all_issues, _, issue_platforms, issue_run_ids, show_platform = (
        resolve_issues_for_filter(
            session,
            project,
            branch,
            pf,
            severity=severity,
            status_filter=status_filter,
            type_filter=type_filter,
            priority_filter=priority_filter,
            q=q,
            sort_by=sort_by,
            order=order,
            classifier_map=classifier_map,
        )
    )

    facets = compute_issue_facets(
        all_for_facets,
        classifier_map,
        severity=severity,
        status_filter=status_filter,
        type_filter=type_filter,
        priority_filter=priority_filter,
    )
    total_effort = compute_total_effort(all_issues, classifier_map)

    if not all_issues and run_id is None:
        return templates.TemplateResponse(
            request,
            "issues_table.html" if not fragment else "partials/issues_rows.html",
            {
                **base_vars,
                "issues": [],
                "total": 0,
                "per_page": 40 if fragment else 80,
                "run_id": None,
                "display_paths": {},
                "issue_platforms": {},
                "issue_run_ids": {},
                "show_platform_badge": False,
                "has_next": False,
                "next_page": 1,
                "facets": facets,
                "issue_groups": [],
                "relative_times": {},
                "total_effort": 0,
            },
        )

    initial_per_page = 80
    per_page = 40 if fragment else initial_per_page
    offset = initial_per_page + max(page - 2, 0) * per_page if fragment else (page - 1) * per_page
    total = len(all_issues)
    issues = all_issues[offset : offset + per_page]

    display_paths = _issues_display_paths(session, project, issues, issue_platforms, pf)
    issue_groups = group_issues_by_file(issues, display_paths)
    relative_times = {i.id: format_relative_time(i.created_at) for i in issues if i.id}

    has_next = offset + per_page < total
    next_page = page + 1

    template_vars = {
        **base_vars,
        "issues": issues,
        "total": total,
        "per_page": per_page,
        "run_id": run_id,
        "display_paths": display_paths,
        "issue_platforms": issue_platforms,
        "issue_run_ids": issue_run_ids,
        "show_platform_badge": show_platform,
        "has_next": has_next,
        "next_page": next_page,
        "facets": facets,
        "issue_groups": issue_groups,
        "relative_times": relative_times,
        "total_effort": total_effort,
    }

    if fragment:
        return templates.TemplateResponse(request, "partials/issues_rows.html", template_vars)
    return templates.TemplateResponse(request, "issues_table.html", template_vars)


@app.get("/ui/issues/{issue_id}", response_class=HTMLResponse)
async def ui_issue_detail(
    request: Request,
    issue_id: int,
    project_id: int,
    branch: str = "",
    platform_filter: str = "windows",
    severity: str = "",
    status_filter: str = "",
    type_filter: str = "",
    priority_filter: str = "",
    q: str = "",
    page: int = 1,
    sort_by: str = "file",
    order: str = "asc",
    session: Session = Depends(get_session),
):
    from pvs_tracker.issues_query import (
        format_relative_time,
        group_issues_by_file,
        resolve_issues_for_filter,
    )
    from pvs_tracker.platforms import normalize_platform_filter

    pf = normalize_platform_filter(platform_filter)
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    issue = session.get(Issue, issue_id)
    if not issue:
        raise HTTPException(404, "Issue not found")

    classifiers = session.exec(select(ErrorClassifier)).all()
    classifier_map, classifier_by_code = build_classifier_maps(classifiers)

    all_issues, run_id, issue_platforms, issue_run_ids, show_platform = (
        resolve_issues_for_filter(
            session,
            project,
            branch,
            pf,
            severity=severity,
            status_filter=status_filter,
            type_filter=type_filter,
            priority_filter=priority_filter,
            q=q,
            sort_by=sort_by,
            order=order,
            classifier_map=classifier_map,
        )
    )

    if not any(i.id == issue.id for i in all_issues):
        raise HTTPException(404, "Issue not in current filter scope")

    nav_limit = 200
    nav_issues = all_issues[:nav_limit]
    nav_display_paths = _issues_display_paths(session, project, nav_issues, issue_platforms, pf)
    nav_groups = group_issues_by_file(nav_issues, nav_display_paths)

    display_paths = _issues_display_paths(session, project, [issue], issue_platforms, pf)
    relative_times = {issue.id: format_relative_time(issue.created_at)} if issue.id else {}

    return templates.TemplateResponse(
        request,
        "issue_detail.html",
        {
            "current_user": _ui_current_user(request),
            "issue": issue,
            "project_id": project_id,
            "branch": branch,
            "platform_filter": pf,
            "severity": severity,
            "status_filter": status_filter,
            "type_filter": type_filter,
            "priority_filter": priority_filter,
            "q": q,
            "page": page,
            "sort_by": sort_by,
            "order": order,
            "run_id": run_id,
            "classifier_map": classifier_map,
            "classifier_by_code": classifier_by_code,
            "display_paths": display_paths,
            "issue_platforms": issue_platforms,
            "issue_run_ids": issue_run_ids,
            "show_platform_badge": show_platform,
            "nav_groups": nav_groups,
            "nav_shown": len(nav_issues),
            "total": len(all_issues),
            "relative_times": relative_times,
        },
    )


@app.get("/ui/issues/{issue_id}/why", response_class=HTMLResponse)
async def ui_issue_why(
    request: Request,
    issue_id: int,
    project_id: int,
    session: Session = Depends(get_session),
):
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    issue = session.get(Issue, issue_id)
    if not issue:
        raise HTTPException(404, "Issue not found")

    classifiers = session.exec(select(ErrorClassifier)).all()
    classifier_map, classifier_by_code = build_classifier_maps(classifiers)
    classifier = resolve_issue_classifier(issue, classifier_map, classifier_by_code)

    doc_url = (
        classifier.doc_url
        if classifier and classifier.doc_url
        else rule_documentation_url(issue.rule_code)
    )
    doc_html, doc_error = await fetch_rule_documentation(issue.rule_code)

    return templates.TemplateResponse(
        request,
        "partials/issue_why.html",
        {
            "issue": issue,
            "classifier": classifier,
            "doc_html": doc_html,
            "doc_error": doc_error,
            "doc_url": doc_url,
        },
    )


def _issue_activity_template_vars(
    request: Request,
    issue: Issue,
    project_id: int,
    session: Session,
) -> dict:
    from pvs_tracker.issue_activity import build_issue_activity_timeline, format_activity_timestamp

    events = build_issue_activity_timeline(session, issue, project_id)
    return {
        "issue": issue,
        "project_id": project_id,
        "current_user": _ui_current_user(request),
        "activity_events": [
            {
                "timestamp": event.timestamp,
                "timestamp_display": format_activity_timestamp(event.timestamp),
                "kind": event.kind,
                "lines": event.lines,
                "actor_name": event.actor_name,
                "actor_email": event.actor_email,
            }
            for event in events
        ],
    }


@app.get("/ui/issues/{issue_id}/activity", response_class=HTMLResponse)
async def ui_issue_activity(
    request: Request,
    issue_id: int,
    project_id: int,
    session: Session = Depends(get_session),
):
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    issue = session.get(Issue, issue_id)
    if not issue:
        raise HTTPException(404, "Issue not found")

    return templates.TemplateResponse(
        request,
        "partials/issue_activity.html",
        _issue_activity_template_vars(request, issue, project_id, session),
    )


@app.post("/ui/issues/{issue_id}/comments", response_class=HTMLResponse)
async def ui_issue_add_comment(
    request: Request,
    issue_id: int,
    project_id: int,
    comment: str = Form(...),
    user: User = Depends(require_auth),
    session: Session = Depends(get_session),
):
    from pvs_tracker.api import log_activity

    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    issue = session.get(Issue, issue_id)
    if not issue:
        raise HTTPException(404, "Issue not found")

    text = comment.strip()
    if not text:
        raise HTTPException(400, "Comment cannot be empty")

    session.add(
        IssueComment(
            issue_id=issue_id,
            user_id=user.id,
            comment=text,
        )
    )
    log_activity(
        session,
        "comment",
        "issue",
        entity_id=issue_id,
        project_id=project_id,
        user_id=user.id,
        details=text[:500],
    )
    session.commit()

    return templates.TemplateResponse(
        request,
        "partials/issue_activity.html",
        _issue_activity_template_vars(request, issue, project_id, session),
    )


@app.post("/ui/upload", response_class=HTMLResponse)
async def upload_report_ui(
    request: Request,
    project_name: str = Form(...),
    file: UploadFile = Form(...),
    source_archive: UploadFile = Form(None),
    code_snapshot: UploadFile = Form(None),
    commit_metadata: UploadFile = Form(None),
    commit: str = Form(None),
    commit_author_name: str = Form(None),
    commit_author_email: str = Form(None),
    release_version: str = Form(None),
    branch: str = Form(None),
    target_platform: str = Form("windows"),
    report_type: str = Form("incremental"),
    session: Session = Depends(get_session),
    _user: User = Depends(require_auth),
):
    """Handle report upload from UI form and redirect to dashboard."""
    from pvs_tracker.quality_gate import evaluate_quality_gate, calculate_run_metrics
    from pvs_tracker.api import log_activity
    from pvs_tracker.incremental import add_issues_to_existing_run
    from pvs_tracker.platforms import normalize_report_type, normalize_target_platform

    platform = normalize_target_platform(target_platform)

    metadata_from_file: dict[str, str] | None = None
    if commit_metadata and commit_metadata.filename:
        try:
            metadata_from_file = parse_commit_metadata_bytes(await commit_metadata.read())
        except ValueError as exc:
            project = session.exec(
                select(Project).where(Project.name == project_name)
            ).first()
            if project:
                from pvs_tracker.project_ci import ensure_project_slug

                ensure_project_slug(session, project)
                return RedirectResponse(
                    url=project_ui_path(
                        project,
                        "dashboard",
                        platform_filter=platform,
                        upload_error=str(exc),
                    ),
                    status_code=303,
                )
            return templates.TemplateResponse(
                request,
                "home.html",
                {
                    "current_user": _ui_current_user(request),
                    "projects": session.exec(select(Project).order_by(Project.name)).all(),
                    "error": str(exc),
                },
                status_code=400,
            )

    commit_fields = merge_commit_upload_fields(
        commit=commit,
        commit_author_name=commit_author_name,
        commit_author_email=commit_author_email,
        release_version=release_version,
        report_type=report_type,
        metadata=metadata_from_file,
        optional_form=_optional_form,
    )
    commit = commit_fields["commit"]
    commit_author_name = commit_fields["commit_author_name"]
    commit_author_email = commit_fields["commit_author_email"]
    release_version = commit_fields["release_version"]
    report_type_val = normalize_report_type(commit_fields.get("report_type"))

    # 1. Read report
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    safe_filename = file.filename or "report.json"
    report_bytes = await file.read()

    # 1.5. Source archive
    source_archive_path = None
    if source_archive and source_archive.filename:
        os.makedirs("source_archives", exist_ok=True)
        archive_filename = source_archive.filename or "source.zip"
        source_archive_path = os.path.join("source_archives", f"{project_name}_{timestamp}_{archive_filename}")
        with open(source_archive_path, "wb") as f:
            f.write(await source_archive.read())

    # 2. Project
    project = session.exec(select(Project).where(Project.name == project_name)).first()
    if not project:
        project = Project(name=project_name)
        session.add(project)
        session.commit()
        session.refresh(project)
        from pvs_tracker.project_ci import ensure_project_slug

        ensure_project_slug(session, project)
    if source_archive_path:
        project.source_archive_path = source_archive_path
        session.commit()

    user_id = _user.id

    # 3. Find existing Run with same commit+branch+platform (status=done)
    existing_run = session.exec(
        select(Run).where(
            Run.project_id == project.id,
            Run.commit == commit,
            Run.branch == branch,
            Run.target_platform == platform,
            Run.status == "done",
        ).order_by(Run.timestamp.desc())
    ).first()

    is_new_run = False
    if existing_run:
        run = existing_run
        run.report_type = report_type_val
        _apply_run_commit_fields(
            run,
            commit=commit,
            commit_author_name=commit_author_name,
            commit_author_email=commit_author_email,
            release_version=release_version,
        )
        store_run_report(session, run.id, f"{safe_filename}_{timestamp}", report_bytes, file.content_type)
        if code_snapshot and code_snapshot.filename:
            merge_code_snapshot(run.id, await code_snapshot.read())
        session.commit()
    else:
        run = Run(
            project_id=project.id,
            branch=branch,
            target_platform=platform,
            report_type=report_type_val,
            report_file=f"db:{safe_filename}",
            **_run_commit_fields(
                commit, commit_author_name, commit_author_email, release_version
            ),
        )
        session.add(run)
        session.commit()
        session.refresh(run)
        store_run_report(session, run.id, safe_filename, report_bytes, file.content_type)
        if code_snapshot and code_snapshot.filename:
            store_code_snapshot(session, run.id, await code_snapshot.read())
        session.commit()
        is_new_run = True

    # 4. Parse and store issues
    try:
        issues = parse_pvs_report_bytes(report_bytes)
        if is_new_run:
            classify_and_store(
                session, project.id, run.id, issues, report_type=report_type_val
            )
            run.status = "done"
        else:
            add_issues_to_existing_run(
                session, project.id, run.id, issues, report_type=report_type_val
            )

        metrics = calculate_run_metrics(session, run.id)
        run.total_issues = metrics["total_issues"]
        run.new_issues = metrics["new_issues"]
        run.fixed_issues = metrics["fixed_issues"]
        _sync_project_release_version(project, release_version)
        session.add(project)
        session.commit()

        qg_result = evaluate_quality_gate(session, project.id, run.id)
        log_activity(
            session,
            "upload",
            "run",
            run.id,
            project.id,
            user_id,
            f"Uploaded report ({platform}, {report_type_val}): {safe_filename}",
        )
        from pvs_tracker.notifications import subscribe_commit_author_notifications

        subscribe_commit_author_notifications(session, project.id, commit_author_email)
        session.commit()

        from pvs_tracker.rest_queue.client import (
            enqueue_jira_sync,
            enqueue_webhook_quality_gate,
            enqueue_webhook_upload,
        )

        enqueue_webhook_quality_gate(project.id, run.id, qg_result)
        enqueue_jira_sync(project.id, run.id)
        enqueue_webhook_upload(project.id, run.id, len(issues))

        return RedirectResponse(
            url=project_ui_path(project, "dashboard", platform_filter=platform),
            status_code=303,
        )
    except Exception as e:
        if is_new_run:
            run.status = "failed"
            session.commit()
        return templates.TemplateResponse(request, "home.html", {
            "current_user": _ui_current_user(request),
            "projects": session.exec(select(Project).order_by(Project.name)).all(),
            "error": f"Failed to parse report: {str(e)}",
        })


@app.get("/ui/settings/profile", response_class=HTMLResponse)
async def profile_settings_page(
    request: Request,
    _user: str = Depends(require_auth),
):
    """User profile and notification settings."""
    return templates.TemplateResponse(
        request,
        "profile_settings.html",
        {"current_user": _ui_current_user(request)},
    )


@app.get("/ui/settings/quality-gates", response_class=HTMLResponse)
async def quality_gates_settings_page(
    request: Request,
    _admin: User = Depends(require_admin),
):
    """Quality gates and PVS warnings catalog (admin only)."""
    return templates.TemplateResponse(
        request,
        "quality_gates_settings.html",
        {"current_user": _ui_current_user(request)},
    )


@app.get("/ui/settings/global", response_class=HTMLResponse)
async def global_settings_page(
    request: Request,
    session: Session = Depends(get_session),
    tab: str = Query("general", pattern="^(general|groups)$"),
    _user: User = Depends(require_auth),
):
    """Global settings page with tabs."""
    # Get or create global settings
    settings = session.exec(select(GlobalSettings).where(GlobalSettings.id == 1)).first()
    if not settings:
        settings = GlobalSettings(id=1)
        session.add(settings)
        session.commit()
        session.refresh(settings)
    
    # Get theme from cookie
    theme = request.cookies.get("theme", "light")
    
    # Load groups if needed
    groups = []
    if tab == "groups":
        from pvs_tracker.models import ProjectGroup
        groups = session.exec(select(ProjectGroup).order_by(ProjectGroup.display_order, ProjectGroup.name)).all()
    
    return templates.TemplateResponse(
        request,
        "global_settings.html",
        {
            "current_user": _ui_current_user(request),
            "settings": settings,
            "theme": theme,
            "active_tab": tab,
            "groups": groups,
        },
    )


@app.post("/api/v1/upload")
async def upload_report_api(
    project_name: str = Form(...),
    file: UploadFile = Form(...),
    source_archive: UploadFile = Form(None),
    code_snapshot: UploadFile = Form(None),
    commit_metadata: UploadFile = Form(None),
    commit: str = Form(None),
    commit_author_name: str = Form(None),
    commit_author_email: str = Form(None),
    release_version: str = Form(None),
    branch: str = Form(None),
    target_platform: str = Form("windows"),
    report_type: str = Form("incremental"),
    session: Session = Depends(get_session),
    _user: User = Depends(require_auth),
):
    """API endpoint for report upload (returns JSON)."""
    from pvs_tracker.quality_gate import evaluate_quality_gate, calculate_run_metrics
    from pvs_tracker.api import log_activity
    from pvs_tracker.incremental import add_issues_to_existing_run
    from pvs_tracker.platforms import normalize_report_type, normalize_target_platform

    platform = normalize_target_platform(target_platform)

    metadata_from_file: dict[str, str] | None = None
    if commit_metadata and commit_metadata.filename:
        try:
            metadata_from_file = parse_commit_metadata_bytes(await commit_metadata.read())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    commit_fields = merge_commit_upload_fields(
        commit=commit,
        commit_author_name=commit_author_name,
        commit_author_email=commit_author_email,
        release_version=release_version,
        report_type=report_type,
        metadata=metadata_from_file,
        optional_form=_optional_form,
    )
    commit = commit_fields["commit"]
    commit_author_name = commit_fields["commit_author_name"]
    commit_author_email = commit_fields["commit_author_email"]
    release_version = commit_fields["release_version"]
    report_type_val = normalize_report_type(commit_fields.get("report_type"))

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    safe_filename = file.filename or "report.json"
    report_bytes = await file.read()

    source_archive_path = None
    if source_archive and source_archive.filename:
        os.makedirs("source_archives", exist_ok=True)
        archive_filename = source_archive.filename or "source.zip"
        source_archive_path = os.path.join("source_archives", f"{project_name}_{timestamp}_{archive_filename}")
        with open(source_archive_path, "wb") as f:
            f.write(await source_archive.read())

    project = session.exec(select(Project).where(Project.name == project_name)).first()
    if not project:
        project = Project(name=project_name)
        session.add(project)
        session.commit()
        session.refresh(project)
        from pvs_tracker.project_ci import ensure_project_slug

        ensure_project_slug(session, project)
    if source_archive_path:
        project.source_archive_path = source_archive_path
        session.commit()

    user_id = _user.id

    existing_run = session.exec(
        select(Run).where(
            Run.project_id == project.id,
            Run.commit == commit,
            Run.branch == branch,
            Run.target_platform == platform,
            Run.status == "done",
        ).order_by(Run.timestamp.desc())
    ).first()

    is_new_run = False
    if existing_run:
        run = existing_run
        run.report_type = report_type_val
        _apply_run_commit_fields(
            run,
            commit=commit,
            commit_author_name=commit_author_name,
            commit_author_email=commit_author_email,
            release_version=release_version,
        )
        store_run_report(session, run.id, f"{safe_filename}_{timestamp}", report_bytes, file.content_type)
        if code_snapshot and code_snapshot.filename:
            merge_code_snapshot(run.id, await code_snapshot.read())
        session.commit()
    else:
        run = Run(
            project_id=project.id,
            branch=branch,
            target_platform=platform,
            report_type=report_type_val,
            report_file=f"db:{safe_filename}",
            **_run_commit_fields(
                commit, commit_author_name, commit_author_email, release_version
            ),
        )
        session.add(run)
        session.commit()
        session.refresh(run)
        store_run_report(session, run.id, safe_filename, report_bytes, file.content_type)
        if code_snapshot and code_snapshot.filename:
            store_code_snapshot(session, run.id, await code_snapshot.read())
        session.commit()
        is_new_run = True

    try:
        issues = parse_pvs_report_bytes(report_bytes)
        if is_new_run:
            classify_and_store(
                session, project.id, run.id, issues, report_type=report_type_val
            )
            run.status = "done"
        else:
            add_issues_to_existing_run(
                session, project.id, run.id, issues, report_type=report_type_val
            )

        metrics = calculate_run_metrics(session, run.id)
        run.total_issues = metrics["total_issues"]
        run.new_issues = metrics["new_issues"]
        run.fixed_issues = metrics["fixed_issues"]
        _sync_project_release_version(project, release_version)
        session.add(project)
        session.commit()

        qg_result = evaluate_quality_gate(session, project.id, run.id)
        log_activity(
            session,
            "upload",
            "run",
            run.id,
            project.id,
            user_id,
            f"Uploaded report ({platform}, {report_type_val}): {safe_filename}",
        )
        from pvs_tracker.notifications import subscribe_commit_author_notifications

        subscribe_commit_author_notifications(session, project.id, commit_author_email)
        session.commit()

        from pvs_tracker.rest_queue.client import (
            enqueue_jira_sync,
            enqueue_smtp_api_upload_notify,
            enqueue_webhook_quality_gate,
            enqueue_webhook_upload,
        )

        enqueue_webhook_quality_gate(project.id, run.id, qg_result)
        enqueue_smtp_api_upload_notify(project.id, run.id, qg_result)
        enqueue_jira_sync(project.id, run.id)
        enqueue_webhook_upload(project.id, run.id, len(issues))

        return {
            "status": "success",
            "run_id": run.id,
            "commit": run.commit,
            "commit_author_name": run.commit_author_name,
            "commit_author_email": run.commit_author_email,
            "release_version": run.release_version,
            "target_platform": platform,
            "report_type": report_type_val,
            "total_issues": len(issues),
            "quality_gate": qg_result,
        }
    except Exception as e:
        if is_new_run:
            run.status = "failed"
            session.commit()
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/v1/projects/{slug}/analysis-callback")
def analysis_callback(
    slug: str,
    commit: str = Form(""),
    version: str = Form(""),
    session: Session = Depends(get_session),
) -> dict[str, str]:
    """Jenkins callback: update last processed changeset / release version."""
    from pvs_tracker.project_ci import get_project_by_slug

    project = get_project_by_slug(session, slug)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if commit.strip():
        project.last_processed_changeset = commit.strip()
    if version.strip():
        project.release_version = version.strip()
    from datetime import datetime

    project.last_analysis_at = datetime.utcnow()
    session.add(project)
    session.commit()
    return {"status": "ok", "project": project.name, "slug": slug}


@app.get("/api/v1/projects/{project_id}/dashboard")
def api_dashboard(project_id: int, branch: str = "", session: Session = Depends(get_session)):
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    from pvs_tracker.dashboard_context import (
        list_project_branches,
        resolve_active_branch,
        sync_project_branch,
    )

    all_runs = session.exec(
        select(Run)
        .where(Run.project_id == project_id, Run.status == "done")
        .order_by(Run.timestamp.desc()),
    ).all()

    branches = list_project_branches(project, all_runs)
    active_branch = resolve_active_branch(project, all_runs, branch)
    if active_branch:
        sync_project_branch(session, project, active_branch)

    # Filter runs by active branch
    run_query = select(Run).where(Run.project_id == project_id, Run.status == "done")
    if active_branch:
        run_query = run_query.where(Run.branch == active_branch)
    run_query = run_query.order_by(Run.timestamp.asc()).limit(10)
    runs = session.exec(run_query).all()

    # Compute cumulative active/fixed counts across runs
    all_fps: set[str] = set()
    fixed_fps: set[str] = set()
    history = []
    for r in runs:
        issues = session.exec(select(Issue).where(Issue.run_id == r.id)).all()
        for i in issues:
            if i.status in ("new", "existing"):
                all_fps.add(i.fingerprint)
            elif i.status == "fixed":
                fixed_fps.add(i.fingerprint)

        active_count = len(all_fps - fixed_fps)
        new_count = len([i for i in issues if i.status == "new"])
        fixed_count = len([i for i in issues if i.status == "fixed"])

        history.append(
            {
                "timestamp": r.timestamp.isoformat(),
                "commit": r.commit,
                "branch": r.branch,
                "release_version": r.release_version or "",
                "commit_author_name": r.commit_author_name,
                "commit_author_email": r.commit_author_email,
                "total": active_count,
                "new": new_count,
                "fixed": fixed_count,
            }
        )

    # Get classifier data for summary
    classifiers = session.exec(select(ErrorClassifier)).all()
    classifier_summary = {
        "total_rules": len(classifiers),
        "by_type": {},
        "by_priority": {},
    }
    for c in classifiers:
        classifier_summary["by_type"][c.type] = classifier_summary["by_type"].get(c.type, 0) + 1
        classifier_summary["by_priority"][c.priority] = classifier_summary["by_priority"].get(c.priority, 0) + 1

    return {
        "project": project.name,
        "branches": branches,
        "active_branch": active_branch,
        "history": history,
        "classifier_summary": classifier_summary,
    }


@app.post("/api/v1/issues/{fingerprint}/ignore")
async def ignore_issue(
    fingerprint: str,
    session: Session = Depends(get_session),
    _user: str = Depends(require_auth),
):
    """Mark an issue as ignored (false positive) across all runs."""
    issues = session.exec(select(Issue).where(Issue.fingerprint == fingerprint)).all()
    if not issues:
        raise HTTPException(404, "Issue not found")
    for issue in issues:
        issue.status = "ignored"
    session.commit()
    return {"status": "ignored", "fingerprint": fingerprint}


@app.put("/api/v1/projects/{project_id}/source-roots")
async def update_source_roots(
    project_id: int,
    request: Request,
    session: Session = Depends(get_session),
    _user: str = Depends(require_auth),
):
    """Update project source root directories (Windows, Linux, macOS)."""
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    body = await request.json()
    source_root_win = body.get("source_root_win")
    source_root_linux = body.get("source_root_linux")
    source_root_macos = body.get("source_root_macos")

    if source_root_win is not None:
        project.source_root_win = source_root_win if source_root_win else None
    if source_root_linux is not None:
        project.source_root_linux = source_root_linux if source_root_linux else None
    if source_root_macos is not None:
        project.source_root_macos = source_root_macos if source_root_macos else None

    session.commit()
    return {
        "status": "success",
        "source_root_win": project.source_root_win,
        "source_root_linux": project.source_root_linux,
        "source_root_macos": project.source_root_macos,
    }


@app.post("/ui/projects/{project_key}/delete")
async def delete_project_ui(
    project_key: str,
    session: Session = Depends(get_session),
    _admin: User = Depends(require_admin),
):
    """Delete a project and its stored analysis data from the UI."""
    from pvs_tracker.project_urls import require_project_by_key

    project = require_project_by_key(session, project_key)
    project_id = project.id

    runs = session.exec(select(Run).where(Run.project_id == project_id)).all()
    run_ids = [run.id for run in runs if run.id is not None]

    if run_ids:
        issues = session.exec(select(Issue).where(Issue.run_id.in_(run_ids))).all()
        issue_ids = [issue.id for issue in issues if issue.id is not None]

        if issue_ids:
            comments = session.exec(select(IssueComment).where(IssueComment.issue_id.in_(issue_ids))).all()
            for comment in comments:
                session.delete(comment)

        for issue in issues:
            session.delete(issue)

        metrics = session.exec(select(MetricSnapshot).where(MetricSnapshot.run_id.in_(run_ids))).all()
        for metric in metrics:
            session.delete(metric)

        reports = session.exec(select(RunReport).where(RunReport.run_id.in_(run_ids))).all()
        for report in reports:
            session.delete(report)

        snapshot_files = session.exec(
            select(CodeSnapshotFile).where(CodeSnapshotFile.run_id.in_(run_ids))
        ).all()
        for snapshot_file in snapshot_files:
            session.delete(snapshot_file)

    members = session.exec(select(ProjectMember).where(ProjectMember.project_id == project_id)).all()
    for member in members:
        session.delete(member)

    activity_logs = session.exec(select(ActivityLog).where(ActivityLog.project_id == project_id)).all()
    for log in activity_logs:
        session.delete(log)

    for run in runs:
        session.delete(run)

    session.delete(project)
    session.commit()
    return RedirectResponse(url="/", status_code=303)


@app.get("/api/v1/issues/{issue_id}/snippet")
async def get_issue_snippet(issue_id: int, session: Session = Depends(get_session)):
    """Возвращает JSON-сниппет: 10 строк до, целевая, 10 после."""
    from pvs_tracker.file_resolver import resolve_source_path
    
    issue = session.get(Issue, issue_id)
    if not issue:
        raise HTTPException(404, "Issue not found")
    if not issue.file_path or issue.file_path.startswith("__analysis__/"):
        return {"lines": [], "start_line": 0, "target_line": 0, "end_line": 0, "language": "txt"}

    run = session.get(Run, issue.run_id)
    project = session.get(Project, run.project_id) if run else None
    
    try:
        abs_path = resolve_source_path(
            project.source_root_win if project else None,
            project.source_root_linux if project else None,
            issue.file_path,
            project.source_root_macos if project else None,
            target_platform=run.target_platform if run else None,
        )
        content = abs_path.read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines()
    except Exception:
        raise HTTPException(404, "File not found or unreadable")

    target = issue.line
    start_idx = max(0, target - 11)  # 10 строк до (индексация с 0)
    end_idx = min(len(lines), target + 10)  # 10 строк после

    return {
        "start_line": start_idx + 1,
        "target_line": target,
        "end_line": end_idx,
        "lines": lines[start_idx:end_idx],
        "language": issue.file_path.rsplit(".", 1)[-1] if "." in issue.file_path else "cpp"
    }
