import os
from datetime import datetime

from fastapi import Depends, FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from sqlmodel import Session, select

from pvs_tracker.models import Issue, Project, Run, SQLModel, create_engine, ErrorClassifier
from pvs_tracker.parser import parse_pvs_report
from pvs_tracker.incremental import classify_and_store
from pvs_tracker.classifier_parser import parse_classifier_csv

# ---------------------------------------------------------------------------
# App & DB
# ---------------------------------------------------------------------------

app = FastAPI(title="PVS-Studio Tracker")
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SECRET_KEY", "dev-change-me"))

BASE_DIR = os.path.dirname(__file__)
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./pvs_tracker.db")

engine = create_engine(DATABASE_URL)
SQLModel.metadata.create_all(engine)


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


@app.get("/ui/projects/{project_id}/dashboard", response_class=HTMLResponse)
async def ui_dashboard(project_id: int, request: Request, session: Session = Depends(get_session)):
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    runs = session.exec(
        select(Run)
        .where(Run.project_id == project_id, Run.status == "done")
        .order_by(Run.timestamp.asc())  # Oldest first for trend chart
        .limit(10),
    ).all()

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
        },
    )


@app.get("/ui/issues", response_class=HTMLResponse)
async def ui_issues(
    request: Request,
    project_id: int,
    severity: str = "",
    status_filter: str = "",
    q: str = "",
    page: int = 1,
    session: Session = Depends(get_session),
):
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
                "severity": severity,
                "status_filter": status_filter,
                "q": q,
            },
        )

    per_page = 50
    query = select(Issue).where(Issue.run_id == latest_run.id)

    if severity:
        query = query.where(Issue.severity == severity)  # type: ignore[arg-type]
    if status_filter:
        query = query.where(Issue.status == status_filter)  # type: ignore[arg-type]
    else:
        # Default: show active issues (new + existing)
        query = query.where(Issue.status.in_(["new", "existing"]))  # type: ignore[attr-defined]
    if q:
        like = f"%{q}%"
        query = query.where(  # type: ignore[call-overload]
            (Issue.file_path.ilike(like)) | (Issue.rule_code.ilike(like)) | (Issue.message.ilike(like))  # type: ignore[attr-defined]
        )

    total_count = session.exec(select(Issue).where(Issue.run_id == latest_run.id)).all()
    issues = session.exec(query.offset((page - 1) * per_page).limit(per_page)).all()

    # Fetch all classifiers for lookup
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
            "severity": severity,
            "status_filter": status_filter,
            "q": q,
            "classifier_map": classifier_map,
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
    commit: str = Form(None),
    branch: str = Form(None),
    session: Session = Depends(get_session),
    _user: str = Depends(require_auth),
):
    """Handle report upload from UI form and redirect to dashboard."""
    # 1. Save report file
    os.makedirs("reports", exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    safe_filename = file.filename or "report.json"
    report_path = os.path.join("reports", f"{project_name}_{timestamp}_{safe_filename}")
    with open(report_path, "wb") as f:
        f.write(await file.read())

    # 2. Ensure project exists
    project = session.exec(select(Project).where(Project.name == project_name)).first()
    if not project:
        project = Project(name=project_name)
        session.add(project)
        session.commit()
        session.refresh(project)

    # 3. Create run record
    run = Run(project_id=project.id, commit=commit, branch=branch, report_file=report_path)
    session.add(run)
    session.commit()
    session.refresh(run)

    # 4. Parse & classify
    try:
        issues = parse_pvs_report(report_path)
        classify_and_store(session, project.id, run.id, issues)
        run.status = "done"
        session.commit()
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


@app.post("/api/v1/upload")
async def upload_report_api(
    project_name: str = Form(...),
    file: UploadFile = Form(...),
    commit: str = Form(None),
    branch: str = Form(None),
    session: Session = Depends(get_session),
    _user: str = Depends(require_auth),
):
    """API endpoint for report upload (returns JSON)."""
    # 1. Save report file
    os.makedirs("reports", exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    safe_filename = file.filename or "report.json"
    report_path = os.path.join("reports", f"{project_name}_{timestamp}_{safe_filename}")
    with open(report_path, "wb") as f:
        f.write(await file.read())

    # 2. Ensure project exists
    project = session.exec(select(Project).where(Project.name == project_name)).first()
    if not project:
        project = Project(name=project_name)
        session.add(project)
        session.commit()
        session.refresh(project)

    # 3. Create run record
    run = Run(project_id=project.id, commit=commit, branch=branch, report_file=report_path)
    session.add(run)
    session.commit()
    session.refresh(run)

    # 4. Parse & classify
    try:
        issues = parse_pvs_report(report_path)
        classify_and_store(session, project.id, run.id, issues)
        run.status = "done"
        session.commit()
        return {"status": "success", "run_id": run.id, "total_issues": len(issues)}
    except Exception as e:
        run.status = "failed"
        session.commit()
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/v1/projects/{project_id}/dashboard")
def api_dashboard(project_id: int, session: Session = Depends(get_session)):
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    runs = session.exec(
        select(Run)
        .where(Run.project_id == project_id, Run.status == "done")
        .order_by(Run.timestamp.asc())  # Oldest first for trend chart
        .limit(10),
    ).all()

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
