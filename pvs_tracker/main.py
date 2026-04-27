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
    SQLModel,
    ErrorClassifier,
    User,
    UserRole,
    GlobalSettings,
)
from pvs_tracker.parser import parse_pvs_report
from pvs_tracker.incremental import classify_and_store
from pvs_tracker.classifier_parser import parse_classifier_csv
from pvs_tracker.db import engine
import pvs_tracker.code_viewer as code_viewer_module
from pvs_tracker.code_viewer import router as code_viewer_router
from pvs_tracker.api import router as api_v2_router
from pvs_tracker.quality_gate import create_default_quality_gate
from pvs_tracker.security import hash_password

import gzip
import json
from pathlib import Path

# Add this near the top with other paths
SNAPSHOTS_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "snapshots")
os.makedirs(SNAPSHOTS_DIR, exist_ok=True)

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
        except Exception:
            pass  # Migration failed, continue anyway


def _initialize_default_data() -> None:
    """Initialize default quality gates and admin user if they don't exist."""
    with Session(engine) as session:
        # Create default quality gate
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


_migrate_database()
_initialize_default_data()


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

    classifiers = parse_classifier_csv(csv_path)
    for clf in classifiers:
        session.add(ErrorClassifier(**clf))
    session.commit()


# Load classifiers on startup
with Session(engine) as init_session:
    _load_error_classifiers(init_session)

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
                "commit": r.commit or "—",
                "branch": r.branch or "—",
                "total": active_count,
                "new": new_count,
                "fixed": fixed_count,
            }
        )

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "current_user": get_current_user(request),
            "project": project,
            "history": history,
            "branches": branches,
            "active_branch": active_branch,
        },
    )


@app.get("/ui/issues", response_class=HTMLResponse)
async def ui_issues(
    request: Request,
    project_id: int,
    branch: str = "",
    severity: str = "",
    status_filter: str = "",
    q: str = "",
    page: int = 1,
    sort_by: str = "file",
    order: str = "asc",
    session: Session = Depends(get_session),
):
    import logging
    logger = logging.getLogger(__name__)
    
    # Determine which run to show issues from
    if branch:
        latest_run = session.exec(
            select(Run)
            .where(Run.project_id == project_id, Run.status == "done", Run.branch == branch)
            .order_by(Run.timestamp.desc())
            .limit(1),
        ).first()
    else:
        latest_run = session.exec(
            select(Run)
            .where(Run.project_id == project_id, Run.status == "done")
            .order_by(Run.timestamp.desc())
            .limit(1),
        ).first()
    
    if not latest_run:
        return templates.TemplateResponse(
            request,
            "issues_table.html",
            {
                "current_user": get_current_user(request),
                "issues": [],
                "total": 0,
                "page": page,
                "per_page": 50,
                "project_id": project_id,
                "branch": branch,
                "severity": severity,
                "status_filter": status_filter,
                "q": q,
                "run_id": None,
                "classifier_map": {},
                "display_paths": {},
                "sort_by": sort_by,
                "order": order,
            },
        )

    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    per_page = 50
    query = select(Issue).where(Issue.run_id == latest_run.id)

    # 🔑 Фильтры
    if severity:
        query = query.where(Issue.severity == severity)
    
    # Фильтр сработает только если передано значение, отличное от пустой строки
    if status_filter and status_filter.strip():
        query = query.where(Issue.status == status_filter)
    else:
        # Если фильтр не выбран — показываем активные (new + existing)
        query = query.where(Issue.status.in_(["new", "existing"]))

    if q:
        like = f"%{q}%"
        query = query.where(
            (Issue.file_path.ilike(like)) | 
            (Issue.rule_code.ilike(like)) | 
            (Issue.message.ilike(like))
        )

    # 🔑 Сортировка
    from sqlalchemy import asc, desc
    sort_map = {
        "status": Issue.status,
        "severity": Issue.severity,
        "rule": Issue.rule_code,
        "file": Issue.file_path,
        "line": Issue.line,
        "message": Issue.message,
    }
    sort_column = sort_map.get(sort_by, Issue.file_path)
    order_func = asc if order == "asc" else desc
    query = query.order_by(order_func(sort_column))

    # 🔑 Получаем ВСЕ issues для подсчёта total
    total_count = session.exec(
        select(Issue).where(Issue.run_id == latest_run.id)
    ).all()
    
    # 🔑 Получаем пагинированные issues
    issues = session.exec(
        query.offset((page - 1) * per_page).limit(per_page)
    ).all()
    
    # 🔑 Логируем для отладки
    logger.info(f"ui_issues: run_id={latest_run.id}, total_in_db={len(total_count)}, filtered_count={len(issues)}")
    if issues:
        logger.info(f"First issue: id={issues[0].id}, status={issues[0].status}, file={issues[0].file_path[:50]}")

    # 🔑 Нормализация путей
    from pvs_tracker.file_resolver import get_effective_source_root, normalize_file_path_for_display
    global_settings = session.exec(select(GlobalSettings).where(GlobalSettings.id == 1)).first()
    
    display_paths = {}
    for issue in issues:
        effective_root = get_effective_source_root(
            project.source_root_win,
            project.source_root_linux,
            global_settings,
        )
        display_paths[issue.id] = normalize_file_path_for_display(issue.file_path, effective_root)

    # Fetch classifiers
    classifiers = session.exec(select(ErrorClassifier)).all()
    classifier_map = {c.id: c for c in classifiers}

    return templates.TemplateResponse(
        request,
        "issues_table.html",
        {
            "current_user": get_current_user(request),
            "issues": issues,
            "total": len(total_count),
            "page": page,
            "per_page": per_page,
            "project_id": project_id,
            "branch": branch,
            "severity": severity,
            "status_filter": status_filter,
            "q": q,
            "classifier_map": classifier_map,
            "run_id": latest_run.id,
            "display_paths": display_paths,
            "sort_by": sort_by,
            "order": order,
        },
    )


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------


@app.post("/ui/upload", response_class=HTMLResponse)
async def upload_report_ui(
    request: Request,
    project_name: str = Form(...),
    file: UploadFile = Form(...),
    source_archive: UploadFile = Form(None),  # Optional source archive
    code_snapshot: UploadFile = Form(None),
    commit: str = Form(None),
    branch: str = Form(None),
    session: Session = Depends(get_session),
    _user: str = Depends(require_auth),
):
    """Handle report upload from UI form and redirect to dashboard."""
    from pvs_tracker.quality_gate import evaluate_quality_gate, calculate_run_metrics
    from pvs_tracker.api import log_activity
    from pvs_tracker.webhooks import trigger_quality_gate_webhook

    # 1. Save report file
    os.makedirs("reports", exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    safe_filename = file.filename or "report.json"
    report_path = os.path.join("reports", f"{project_name}_{timestamp}_{safe_filename}")
    with open(report_path, "wb") as f:
        f.write(await file.read())

    # 1.5. Save source archive if provided
    source_archive_path = None
    if source_archive and source_archive.filename:
        os.makedirs("source_archives", exist_ok=True)
        archive_filename = source_archive.filename or "source.zip"
        source_archive_path = os.path.join("source_archives", f"{project_name}_{timestamp}_{archive_filename}")
        with open(source_archive_path, "wb") as f:
            f.write(await source_archive.read())

    # 2. Ensure project exists
    project = session.exec(select(Project).where(Project.name == project_name)).first()
    if not project:
        project = Project(name=project_name)
        session.add(project)
        session.commit()
        session.refresh(project)
    
    # Update source archive path if provided
    if source_archive_path:
        project.source_archive_path = source_archive_path
        session.commit()

    # Get user ID for activity logging
    user = session.exec(select(User).where(User.username == _user)).first()
    user_id = user.id if user else None

    # 3. Create run record (получаем run.id до сохранения снапшота)
    run = Run(project_id=project.id, commit=commit, branch=branch, report_file=report_path)
    session.add(run)
    session.commit()
    session.refresh(run)

    # 🔑 Сохраняем code snapshot, если приложен
    if code_snapshot and code_snapshot.filename:
        from pathlib import Path
        snapshot_dir = Path(os.path.join(BASE_DIR, "..", "data", "snapshots"))
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        snapshot_path = snapshot_dir / f"{run.id}.json.gz"
        with open(snapshot_path, "wb") as f:
            f.write(await code_snapshot.read())
        # log optional: print(f"✅ Saved snapshot for run {run.id} -> {snapshot_path}")

    # 4. Parse & classify
    try:
        issues = parse_pvs_report(report_path)
        classify_and_store(session, project.id, run.id, issues)
        run.status = "done"
        
        # Calculate metrics and update run stats
        metrics = calculate_run_metrics(session, run.id)
        run.total_issues = metrics["total_issues"]
        run.new_issues = metrics["new_issues"]
        run.fixed_issues = metrics["fixed_issues"]
        session.commit()
        
        # Evaluate quality gate
        qg_result = evaluate_quality_gate(session, project.id, run.id)
        
        # Log activity
        log_activity(session, "upload", "run", run.id, project.id, user_id, 
                    f"Uploaded report: {safe_filename}")
        session.commit()
        
        # Trigger webhook (async, non-blocking)
        import asyncio
        asyncio.create_task(trigger_quality_gate_webhook(session, project.id, run.id, qg_result))
        
        # Redirect to project dashboard
        return RedirectResponse(
            url=f"/ui/projects/{project.id}/dashboard",
            status_code=303,
        )
    except Exception as e:
        run.status = "failed"
        session.commit()
        # Show error on home page
        return templates.TemplateResponse(
            request,
            "home.html",
            {
                "current_user": get_current_user(request),
                "projects": session.exec(select(Project).order_by(Project.name)).all(),
                "error": f"Failed to parse report: {str(e)}",
            },
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
    source_archive: UploadFile = Form(None),  # Optional source archive
    code_snapshot: UploadFile = Form(None),  # 🔑 Новое поле
    commit: str = Form(None),
    branch: str = Form(None),
    session: Session = Depends(get_session),
    _user: str = Depends(require_auth),
):
    """API endpoint for report upload (returns JSON)."""
    from pvs_tracker.quality_gate import evaluate_quality_gate, calculate_run_metrics
    from pvs_tracker.api import log_activity
    from pvs_tracker.webhooks import trigger_quality_gate_webhook

    # 1. Save report file
    os.makedirs("reports", exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    safe_filename = file.filename or "report.json"
    report_path = os.path.join("reports", f"{project_name}_{timestamp}_{safe_filename}")
    with open(report_path, "wb") as f:
        f.write(await file.read())

    # 1.5. Save source archive if provided
    source_archive_path = None
    if source_archive and source_archive.filename:
        os.makedirs("source_archives", exist_ok=True)
        archive_filename = source_archive.filename or "source.zip"
        source_archive_path = os.path.join("source_archives", f"{project_name}_{timestamp}_{archive_filename}")
        with open(source_archive_path, "wb") as f:
            f.write(await source_archive.read())

    # 2. Ensure project exists
    project = session.exec(select(Project).where(Project.name == project_name)).first()
    if not project:
        project = Project(name=project_name)
        session.add(project)
        session.commit()
        session.refresh(project)
    
    # Update source archive path if provided
    if source_archive_path:
        project.source_archive_path = source_archive_path
        session.commit()

    # Get user ID for activity logging
    user = session.exec(select(User).where(User.username == _user)).first()
    user_id = user.id if user else None

    # 3. Create run record
    run = Run(project_id=project.id, commit=commit, branch=branch, report_file=report_path)
    session.add(run)
    session.commit()
    session.refresh(run)

    # 🔑 Сохраняем snapshot если приложен
    if code_snapshot and code_snapshot.filename:
        snapshot_path = Path(SNAPSHOTS_DIR) / f"{run.id}.json.gz"
        with open(snapshot_path, "wb") as f:
            f.write(await code_snapshot.read())

    # 4. Parse & classify
    try:
        issues = parse_pvs_report(report_path)
        classify_and_store(session, project.id, run.id, issues)
        run.status = "done"
        
        # Calculate metrics and update run stats
        metrics = calculate_run_metrics(session, run.id)
        run.total_issues = metrics["total_issues"]
        run.new_issues = metrics["new_issues"]
        run.fixed_issues = metrics["fixed_issues"]
        session.commit()
        
        # Evaluate quality gate
        qg_result = evaluate_quality_gate(session, project.id, run.id)
        
        # Log activity
        log_activity(session, "upload", "run", run.id, project.id, user_id,
                    f"Uploaded report: {safe_filename}")
        session.commit()
        
        # Trigger webhook (async, non-blocking)
        import asyncio
        asyncio.create_task(trigger_quality_gate_webhook(session, project.id, run.id, qg_result))
        
        return {
            "status": "success",
            "run_id": run.id,
            "total_issues": len(issues),
            "quality_gate": qg_result,
        }
    except Exception as e:
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
    """Update project source root directories (Windows and Linux)."""
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    body = await request.json()
    source_root_win = body.get("source_root_win")
    source_root_linux = body.get("source_root_linux")

    # Update fields if provided
    if source_root_win is not None:
        project.source_root_win = source_root_win if source_root_win else None
    if source_root_linux is not None:
        project.source_root_linux = source_root_linux if source_root_linux else None

    session.commit()
    return {
        "status": "success",
        "source_root_win": project.source_root_win,
        "source_root_linux": project.source_root_linux,
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
