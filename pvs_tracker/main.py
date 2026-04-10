import os
from datetime import datetime

from fastapi import Depends, FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from sqlmodel import Session, select

from pvs_tracker.models import Issue, Project, Run, SQLModel, create_engine
from pvs_tracker.parser import parse_pvs_report
from pvs_tracker.incremental import classify_and_store

# ---------------------------------------------------------------------------
# App & DB
# ---------------------------------------------------------------------------

app = FastAPI(title="PVS-Studio Tracker")
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SECRET_KEY", "dev-change-me"))

BASE_DIR = os.path.dirname(__file__)
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./pvs_tracker.db")

engine = create_engine(DATABASE_URL)
SQLModel.metadata.create_all(engine)

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
        .where(Run.project_id == project_id)
        .order_by(Run.timestamp.desc())
        .limit(10),
    ).all()

    history = []
    for r in runs:
        issues = session.exec(select(Issue).where(Issue.run_id == r.id)).all()
        history.append(
            {
                "timestamp": r.timestamp.isoformat(),
                "commit": r.commit or "—",
                "branch": r.branch or "—",
                "total": len([i for i in issues if i.status in ("new", "existing")]),
                "new": len([i for i in issues if i.status == "new"]),
                "fixed": len([i for i in issues if i.status == "fixed"]),
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
    status_filter: str = "existing",
    q: str = "",
    page: int = 1,
    session: Session = Depends(get_session),
):
    # Find the latest run for this project
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
    if q:
        like = f"%{q}%"
        query = query.where(  # type: ignore[call-overload]
            (Issue.file_path.ilike(like)) | (Issue.rule_code.ilike(like)) | (Issue.message.ilike(like))  # type: ignore[attr-defined]
        )

    total_count = session.exec(select(Issue).where(Issue.run_id == latest_run.id)).all()
    issues = session.exec(query.offset((page - 1) * per_page).limit(per_page)).all()

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
        .where(Run.project_id == project_id)
        .order_by(Run.timestamp.desc())
        .limit(10),
    ).all()

    trends = []
    for r in runs:
        issues = session.exec(select(Issue).where(Issue.run_id == r.id)).all()
        trends.append(
            {
                "timestamp": r.timestamp.isoformat(),
                "commit": r.commit,
                "branch": r.branch,
                "total": len([i for i in issues if i.status in ("new", "existing")]),
                "new": len([i for i in issues if i.status == "new"]),
                "fixed": len([i for i in issues if i.status == "fixed"]),
            }
        )
    return {"project": project.name, "history": trends}


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
