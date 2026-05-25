import os
from datetime import datetime

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
)
from pvs_tracker.parser import parse_pvs_report_bytes
from pvs_tracker.artifact_storage import store_code_snapshot, store_run_report
from pvs_tracker.incremental import classify_and_store
from pvs_tracker.classifier_parser import parse_classifier_csv
from pvs_tracker.db import engine
import pvs_tracker.code_viewer as code_viewer_module
from pvs_tracker.code_viewer import merge_code_snapshot, router as code_viewer_router
from pvs_tracker.api import router as api_v2_router
from pvs_tracker.quality_gate import create_default_quality_gate, evaluate_quality_gate
from pvs_tracker.security import hash_password

# ---------------------------------------------------------------------------
# App & DB
# ---------------------------------------------------------------------------

app = FastAPI(title="PVS-Studio Tracker")
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SECRET_KEY", "dev-change-me"))

BASE_DIR = os.path.dirname(__file__)


def _migrate_database() -> None:
    """Apply schema migrations for existing databases."""
    # Create all tables (safe if they already exist)
    SQLModel.metadata.create_all(engine)

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
                ):
                    try:
                        conn.execute(text(col_sql))
                        conn.commit()
                    except Exception:
                        pass
        except Exception:
            pass  # Migration failed, continue anyway

        _backfill_cross_platform_fps(session)


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
                role=UserRole.ADMIN,
                is_active=True,
            )
            session.add(admin_user)
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


_migrate_database()
_initialize_default_data()

with Session(engine) as _lang_session:
    from pvs_tracker.warnings_catalog import backfill_classifier_languages

    backfill_classifier_languages(_lang_session)


# Templates
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

# Register code_viewer router and pass templates reference
code_viewer_module.templates = templates
app.include_router(code_viewer_router)

# Register API v2 router (SonarQube-like features)
app.include_router(api_v2_router)

# Static files
STATIC_DIR = os.path.join(os.path.dirname(BASE_DIR), "static")
if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------


def get_session():
    with Session(engine) as session:
        yield session


def get_current_user(request: Request) -> str | None:
    return request.session.get("user")


def require_auth(user: str | None = Depends(get_current_user)) -> str:
    if not user:
        raise HTTPException(401, "Authentication required")
    return user


def require_admin_user(user: str = Depends(require_auth)) -> str:
    if user != "admin":
        raise HTTPException(403, "Admin access required")
    return user


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
    # MVP: simple bypass auth — accept any non-empty credentials.
    # Replace with real LDAP (see auth.py) when ready.
    if not username or not password:
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Username and password are required"},
        )
    request.session["user"] = username
    return RedirectResponse(url="/", status_code=303)


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/", status_code=303)


# ---------------------------------------------------------------------------
# UI routes
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def home(request: Request, session: Session = Depends(get_session)):
    projects = session.exec(select(Project).order_by(Project.name)).all()
    return templates.TemplateResponse(
        request,
        "home.html",
        {"current_user": get_current_user(request), "projects": projects},
    )


@app.post("/ui/projects", response_class=HTMLResponse)
async def create_project_ui(
    request: Request,
    project_name: str = Form(...),
    branch: str = Form("main"),
    language: str = Form("c++"),
    file: UploadFile = Form(None),
    code_snapshot: UploadFile = Form(None),
    commit: str = Form(None),
    session: Session = Depends(get_session),
    _user: str = Depends(require_auth),
):
    """Create a project from the web UI, optionally with an initial report."""
    name = project_name.strip()
    if not name:
        projects = session.exec(select(Project).order_by(Project.name)).all()
        return templates.TemplateResponse(
            request,
            "home.html",
            {
                "current_user": get_current_user(request),
                "projects": projects,
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
                commit=commit,
                branch=(branch or project.git_branch or "main").strip() or "main",
                session=session,
                _user=_user,
            )
        return RedirectResponse(url=f"/ui/projects/{project.id}/dashboard", status_code=303)

    default_branch = (branch or "main").strip() or "main"
    project = Project(name=name, language=language or "c++", git_branch=default_branch)
    session.add(project)
    session.commit()
    session.refresh(project)

    if file and file.filename:
        return await upload_report_ui(
            request=request,
            project_name=name,
            file=file,
            source_archive=None,
            code_snapshot=code_snapshot,
            commit=commit,
            branch=default_branch,
            session=session,
            _user=_user,
        )

    return RedirectResponse(url=f"/ui/projects/{project.id}/dashboard", status_code=303)


@app.get("/ui/projects/{project_id}/dashboard", response_class=HTMLResponse)
async def ui_dashboard(
    project_id: int,
    request: Request,
    branch: str = "",
    platform_filter: str = "windows",
    session: Session = Depends(get_session),
):
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    # Collect all distinct branches from runs
    all_runs = session.exec(
        select(Run)
        .where(Run.project_id == project_id, Run.status == "done")
        .order_by(Run.timestamp.desc()),
    ).all()

    branches: list[str] = []
    for r in all_runs:
        b = (r.branch or "").strip()
        if b and b not in branches:
            branches.append(b)
    default_branch = (project.git_branch or "").strip()
    if default_branch and default_branch not in branches:
        branches.append(default_branch)

    # Determine active branch: explicit param > main > master > first available
    if branch:
        active_branch = branch
    elif "main" in branches:
        active_branch = "main"
    elif "master" in branches:
        active_branch = "master"
    elif branches:
        active_branch = branches[0]
    else:
        active_branch = ""

    from pvs_tracker.dashboard_history import build_dashboard_histories
    from pvs_tracker.platforms import normalize_platform_filter
    from pvs_tracker.run_queries import get_latest_run

    pf = normalize_platform_filter(platform_filter)
    history, history_by_platform = build_dashboard_histories(
        session, project_id, active_branch, pf
    )

    qg_result: dict = {"status": "passed", "conditions": [], "summary": {"new_in_gate": 0}}
    latest_for_qg = None
    if pf in ("windows", "linux", "macos"):
        latest_for_qg = get_latest_run(session, project_id, active_branch, pf)
    elif history:
        run_query = select(Run).where(Run.project_id == project_id, Run.status == "done")
        if active_branch:
            run_query = run_query.where(Run.branch == active_branch)
        latest_for_qg = session.exec(run_query.order_by(Run.timestamp.desc()).limit(1)).first()
    if latest_for_qg and latest_for_qg.id is not None:
        qg_result = evaluate_quality_gate(session, project_id, latest_for_qg.id)

    quality_gates = session.exec(select(QualityGate).order_by(QualityGate.name)).all()

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "current_user": get_current_user(request),
            "project": project,
            "history": history,
            "history_by_platform": history_by_platform,
            "branches": branches,
            "active_branch": active_branch,
            "platform_filter": pf,
            "qg_result": qg_result,
            "quality_gates": quality_gates,
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


@app.get("/ui/projects/{project_id}/trends-fragment", response_class=HTMLResponse)
async def ui_trends_fragment(
    project_id: int,
    request: Request,
    branch: str = "",
    platform_filter: str = "windows",
    session: Session = Depends(get_session),
):
    """HTMX/HTML fragment: trends KPI + chart area for selected platform."""
    from pvs_tracker.dashboard_context import build_platform_metrics, resolve_active_branch
    from pvs_tracker.platforms import normalize_platform_filter

    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

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


@app.get("/ui/issues", response_class=HTMLResponse)
async def ui_issues(
    request: Request,
    project_id: int,
    branch: str = "",
    platform_filter: str = "windows",
    severity: str = "",
    status_filter: str = "",
    q: str = "",
    page: int = 1,
    sort_by: str = "file",
    order: str = "asc",
    fragment: bool = False,
    session: Session = Depends(get_session),
):
    from pvs_tracker.file_resolver import get_effective_source_root, normalize_file_path_for_display
    from pvs_tracker.issues_query import resolve_issues_for_filter
    from pvs_tracker.platforms import normalize_platform_filter

    pf = normalize_platform_filter(platform_filter)
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    classifiers = session.exec(select(ErrorClassifier)).all()
    classifier_map = {c.id: c for c in classifiers}

    empty_vars = {
        "current_user": get_current_user(request),
        "issues": [],
        "total": 0,
        "page": page,
        "per_page": 25 if fragment else 50,
        "project_id": project_id,
        "branch": branch,
        "platform_filter": pf,
        "severity": severity,
        "status_filter": status_filter,
        "q": q,
        "run_id": None,
        "classifier_map": classifier_map,
        "display_paths": {},
        "issue_platforms": {},
        "issue_run_ids": {},
        "show_platform_badge": False,
        "sort_by": sort_by,
        "order": order,
        "has_next": False,
        "next_page": 1,
    }

    all_issues, run_id, issue_platforms, issue_run_ids, show_platform = (
        resolve_issues_for_filter(
            session,
            project,
            branch,
            pf,
            severity=severity,
            status_filter=status_filter,
            q=q,
            sort_by=sort_by,
            order=order,
            classifier_map=classifier_map,
        )
    )

    if not all_issues and run_id is None:
        return templates.TemplateResponse(
            request,
            "issues_table.html" if not fragment else "partials/issues_rows.html",
            empty_vars,
        )

    initial_per_page = 50
    per_page = 25 if fragment else initial_per_page
    offset = initial_per_page + max(page - 2, 0) * per_page if fragment else (page - 1) * per_page
    total = len(all_issues)
    issues = all_issues[offset : offset + per_page]

    global_settings = session.exec(select(GlobalSettings).where(GlobalSettings.id == 1)).first()
    display_paths: dict[int, str] = {}
    for issue in issues:
        from pvs_tracker.platforms import PLATFORMS

        plat = issue_platforms.get(issue.id)
        if not plat:
            plat = pf if pf in PLATFORMS else "windows"
        effective_root = get_effective_source_root(
            project.source_root_win,
            project.source_root_linux,
            global_settings,
            project.source_root_macos,
            platform=plat,
        )
        display_paths[issue.id] = normalize_file_path_for_display(issue.file_path, effective_root)

    has_next = offset + per_page < total
    next_page = page + 1

    template_vars = {
        "current_user": get_current_user(request),
        "issues": issues,
        "total": total,
        "page": page,
        "per_page": per_page,
        "project_id": project_id,
        "branch": branch,
        "platform_filter": pf,
        "severity": severity,
        "status_filter": status_filter,
        "q": q,
        "run_id": run_id,
        "classifier_map": classifier_map,
        "display_paths": display_paths,
        "issue_platforms": issue_platforms,
        "issue_run_ids": issue_run_ids,
        "show_platform_badge": show_platform,
        "sort_by": sort_by,
        "order": order,
        "has_next": has_next,
        "next_page": next_page,
    }

    if fragment:
        return templates.TemplateResponse(request, "partials/issues_rows.html", template_vars)
    return templates.TemplateResponse(request, "issues_table.html", template_vars)


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------


@app.post("/ui/upload", response_class=HTMLResponse)
async def upload_report_ui(
    request: Request,
    project_name: str = Form(...),
    file: UploadFile = Form(...),
    source_archive: UploadFile = Form(None),
    code_snapshot: UploadFile = Form(None),
    commit: str = Form(None),
    branch: str = Form(None),
    target_platform: str = Form("windows"),
    session: Session = Depends(get_session),
    _user: str = Depends(require_auth),
):
    """Handle report upload from UI form and redirect to dashboard."""
    from pvs_tracker.quality_gate import evaluate_quality_gate, calculate_run_metrics
    from pvs_tracker.api import log_activity
    from pvs_tracker.webhooks import trigger_quality_gate_webhook
    from pvs_tracker.incremental import add_issues_to_existing_run
    from pvs_tracker.platforms import normalize_target_platform

    platform = normalize_target_platform(target_platform)

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
    if source_archive_path:
        project.source_archive_path = source_archive_path
        session.commit()

    user = session.exec(select(User).where(User.username == _user)).first()
    user_id = user.id if user else None

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
        store_run_report(session, run.id, f"{safe_filename}_{timestamp}", report_bytes, file.content_type)
        if code_snapshot and code_snapshot.filename:
            merge_code_snapshot(run.id, await code_snapshot.read())
        session.commit()
    else:
        run = Run(
            project_id=project.id,
            commit=commit,
            branch=branch,
            target_platform=platform,
            report_file=f"db:{safe_filename}",
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
            classify_and_store(session, project.id, run.id, issues)
            run.status = "done"
        else:
            add_issues_to_existing_run(session, project.id, run.id, issues)

        metrics = calculate_run_metrics(session, run.id)
        run.total_issues = metrics["total_issues"]
        run.new_issues = metrics["new_issues"]
        run.fixed_issues = metrics["fixed_issues"]
        session.commit()

        qg_result = evaluate_quality_gate(session, project.id, run.id)
        log_activity(
            session,
            "upload",
            "run",
            run.id,
            project.id,
            user_id,
            f"Uploaded report ({platform}): {safe_filename}",
        )
        session.commit()

        import asyncio
        asyncio.create_task(trigger_quality_gate_webhook(session, project.id, run.id, qg_result))

        return RedirectResponse(
            url=f"/ui/projects/{project.id}/dashboard?platform_filter={platform}",
            status_code=303,
        )
    except Exception as e:
        if is_new_run:
            run.status = "failed"
            session.commit()
        return templates.TemplateResponse(request, "home.html", {
            "current_user": get_current_user(request),
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
        {"current_user": get_current_user(request)},
    )


@app.get("/ui/settings/quality-gates", response_class=HTMLResponse)
async def quality_gates_settings_page(
    request: Request,
    _admin: str = Depends(require_admin_user),
):
    """Quality gates and PVS warnings catalog (admin only)."""
    return templates.TemplateResponse(
        request,
        "quality_gates_settings.html",
        {"current_user": get_current_user(request)},
    )


@app.get("/ui/settings/global", response_class=HTMLResponse)
async def global_settings_page(
    request: Request,
    session: Session = Depends(get_session),
    _user: str = Depends(require_auth),
):
    """Global settings page."""
    # Get or create global settings
    settings = session.exec(select(GlobalSettings).where(GlobalSettings.id == 1)).first()
    if not settings:
        # 🔑 Создаём с явным указанием полей (без default_git_branch)
        settings = GlobalSettings(
            id=1,
            default_source_root_win=None,
            default_source_root_linux=None,
        )
        session.add(settings)
        session.commit()
        session.refresh(settings)
    
    # Get current theme from cookie or default
    theme = request.cookies.get("theme", "light")
    
    return templates.TemplateResponse(
        request,
        "global_settings.html",
        {
            "current_user": get_current_user(request),
            "settings": settings,
            "theme": theme,
        },
    )


@app.post("/api/v1/upload")
async def upload_report_api(
    project_name: str = Form(...),
    file: UploadFile = Form(...),
    source_archive: UploadFile = Form(None),
    code_snapshot: UploadFile = Form(None),
    commit: str = Form(None),
    branch: str = Form(None),
    target_platform: str = Form("windows"),
    session: Session = Depends(get_session),
    _user: str = Depends(require_auth),
):
    """API endpoint for report upload (returns JSON)."""
    from pvs_tracker.quality_gate import evaluate_quality_gate, calculate_run_metrics
    from pvs_tracker.api import log_activity
    from pvs_tracker.webhooks import trigger_quality_gate_webhook
    from pvs_tracker.incremental import add_issues_to_existing_run
    from pvs_tracker.platforms import normalize_target_platform

    platform = normalize_target_platform(target_platform)

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
    if source_archive_path:
        project.source_archive_path = source_archive_path
        session.commit()

    user = session.exec(select(User).where(User.username == _user)).first()
    user_id = user.id if user else None

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
        store_run_report(session, run.id, f"{safe_filename}_{timestamp}", report_bytes, file.content_type)
        if code_snapshot and code_snapshot.filename:
            merge_code_snapshot(run.id, await code_snapshot.read())
        session.commit()
    else:
        run = Run(
            project_id=project.id,
            commit=commit,
            branch=branch,
            target_platform=platform,
            report_file=f"db:{safe_filename}",
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
            classify_and_store(session, project.id, run.id, issues)
            run.status = "done"
        else:
            add_issues_to_existing_run(session, project.id, run.id, issues)

        metrics = calculate_run_metrics(session, run.id)
        run.total_issues = metrics["total_issues"]
        run.new_issues = metrics["new_issues"]
        run.fixed_issues = metrics["fixed_issues"]
        session.commit()

        qg_result = evaluate_quality_gate(session, project.id, run.id)
        log_activity(
            session,
            "upload",
            "run",
            run.id,
            project.id,
            user_id,
            f"Uploaded report ({platform}): {safe_filename}",
        )
        session.commit()

        import asyncio
        from pvs_tracker.notifications import schedule_api_upload_notifications

        asyncio.create_task(trigger_quality_gate_webhook(session, project.id, run.id, qg_result))
        asyncio.create_task(
            schedule_api_upload_notifications(project.id, run.id, qg_result)
        )

        return {
            "status": "success",
            "run_id": run.id,
            "target_platform": platform,
            "total_issues": len(issues),
            "quality_gate": qg_result,
        }
    except Exception as e:
        if is_new_run:
            run.status = "failed"
            session.commit()
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/v1/projects/{project_id}/dashboard")
def api_dashboard(project_id: int, branch: str = "", session: Session = Depends(get_session)):
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    # Collect all distinct branches from runs
    all_runs = session.exec(
        select(Run)
        .where(Run.project_id == project_id, Run.status == "done")
        .order_by(Run.timestamp.desc()),
    ).all()

    branches: list[str] = []
    for r in all_runs:
        b = (r.branch or "").strip()
        if b and b not in branches:
            branches.append(b)
    default_branch = (project.git_branch or "").strip()
    if default_branch and default_branch not in branches:
        branches.append(default_branch)

    # Determine active branch: explicit param > main > master > first available
    if branch:
        active_branch = branch
    elif "main" in branches:
        active_branch = "main"
    elif "master" in branches:
        active_branch = "master"
    elif branches:
        active_branch = branches[0]
    else:
        active_branch = ""

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


@app.post("/ui/projects/{project_id}/delete")
async def delete_project_ui(
    project_id: int,
    session: Session = Depends(get_session),
    _admin: str = Depends(require_admin_user),
):
    """Delete a project and its stored analysis data from the UI."""
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

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
