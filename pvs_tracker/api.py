"""Comprehensive API routes for SonarQube-like PVS-Studio Tracker."""

from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select, func
from pydantic import BaseModel, Field
import csv
import io

from pvs_tracker.models import (
    Project, Run, Issue, ErrorClassifier, User, UserRole,
    ProjectMember, QualityGate, QualityGateCondition, GlobalSettings,
    IssueComment, ActivityLog, MetricSnapshot, IssueResolution,
    RunReport, CodeSnapshotFile,
)
from pvs_tracker.auth_service import (
    require_auth, require_admin, require_role, create_user,
    authenticate_user, create_access_token, get_current_user,
    can_access_project, can_modify_project
)
from pvs_tracker.quality_gate import (
    evaluate_quality_gate, calculate_run_metrics,
    create_default_quality_gate
)
from pvs_tracker.db import get_session
from pvs_tracker.security import hash_password

router = APIRouter(prefix="/api/v2")


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    email: Optional[str] = None
    password: str = Field(min_length=6)
    role: UserRole = UserRole.VIEWER


class UserUpdate(BaseModel):
    email: Optional[str] = None
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None


class LoginRequest(BaseModel):
    username: str
    password: str


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    language: str = "c++"
    description: Optional[str] = None
    source_root_win: Optional[str] = None
    source_root_linux: Optional[str] = None
    git_url: Optional[str] = None
    git_branch: str = "main"
    quality_gate_id: Optional[int] = None


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    language: Optional[str] = None
    description: Optional[str] = None
    source_root_win: Optional[str] = None
    source_root_linux: Optional[str] = None
    git_url: Optional[str] = None
    git_branch: Optional[str] = None
    quality_gate_id: Optional[int] = None


class QualityGateCreate(BaseModel):
    name: str
    is_default: bool = False


class QualityGateConditionCreate(BaseModel):
    metric: str
    operator: str
    threshold: int
    error_policy: str = "error"


class IssueCommentCreate(BaseModel):
    comment: str = Field(min_length=1, max_length=5000)


class IssueResolutionUpdate(BaseModel):
    resolution: IssueResolution
    comment: Optional[str] = None


class ProjectMemberAdd(BaseModel):
    user_id: int
    role: UserRole = UserRole.VIEWER


# ---------------------------------------------------------------------------
# Activity logging helper
# ---------------------------------------------------------------------------

def log_activity(
    session: Session,
    action: str,
    entity_type: str,
    entity_id: Optional[int] = None,
    project_id: Optional[int] = None,
    user_id: Optional[int] = None,
    details: Optional[str] = None,
):
    """Log an activity to the audit trail."""
    log = ActivityLog(
        project_id=project_id,
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details=details,
    )
    session.add(log)


# ---------------------------------------------------------------------------
# Authentication & User Management API
# ---------------------------------------------------------------------------

@router.post("/auth/login")
async def api_login(body: LoginRequest, db: Session = Depends(lambda: None)):
    """Authenticate user and return JWT token."""
    from sqlmodel import Session
    from pvs_tracker.db import engine
    with Session(engine) as db_session:
        user = authenticate_user(db_session, body.username, body.password)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid credentials")

        token = create_access_token(data={"sub": str(user.id), "username": user.username})
        return {
            "access_token": token,
            "token_type": "bearer",
            "user": {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "role": user.role,
            },
        }


@router.get("/users/me")
async def get_me(user: User = Depends(require_auth)):
    """Get current user profile."""
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "role": user.role,
        "is_active": user.is_active,
        "created_at": user.created_at,
        "last_login": user.last_login,
    }


@router.get("/users", dependencies=[Depends(require_admin)])
async def list_users(session: Session = Depends(lambda s: None)):
    """List all users (admin only)."""
    from sqlmodel import Session
    from pvs_tracker.db import engine
    with Session(engine) as db_session:
        users = db_session.exec(select(User).order_by(User.username)).all()
        return [
            {
                "id": u.id,
                "username": u.username,
                "email": u.email,
                "role": u.role,
                "is_active": u.is_active,
                "created_at": u.created_at,
            }
            for u in users
        ]


@router.post("/users", dependencies=[Depends(require_admin)])
async def create_user_api(body: UserCreate, session: Session = Depends(lambda s: None)):
    """Create a new user (admin only)."""
    from sqlmodel import Session
    from pvs_tracker.db import engine
    with Session(engine) as db_session:
        # Check if username already exists
        existing = db_session.exec(select(User).where(User.username == body.username)).first()
        if existing:
            raise HTTPException(status_code=400, detail="Username already exists")
        
        user = create_user(db_session, body.username, body.password, body.email, body.role)
        return {"id": user.id, "username": user.username, "role": user.role}


@router.patch("/users/{user_id}", dependencies=[Depends(require_admin)])
async def update_user_api(user_id: int, body: UserUpdate, session: Session = Depends(lambda s: None)):
    """Update user (admin only)."""
    from sqlmodel import Session
    from pvs_tracker.db import engine
    with Session(engine) as db_session:
        user = db_session.get(User, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        if body.email is not None:
            user.email = body.email
        if body.role is not None:
            user.role = body.role
        if body.is_active is not None:
            user.is_active = body.is_active
        
        db_session.add(user)
        db_session.commit()
        return {"id": user.id, "username": user.username, "role": user.role, "is_active": user.is_active}


# ---------------------------------------------------------------------------
# Project Management API
# ---------------------------------------------------------------------------

@router.get("/projects")
async def list_projects(
    user: User = Depends(require_auth),
    session: Session = Depends(lambda: None),
):
    """List all projects accessible to the user."""
    from sqlmodel import Session
    from pvs_tracker.db import engine
    with Session(engine) as db_session:
        # Admin sees all, others see projects they have access to
        if user.role == UserRole.ADMIN:
            projects = db_session.exec(select(Project).order_by(Project.name)).all()
        else:
            # Get projects where user is a member
            memberships = db_session.exec(
                select(ProjectMember).where(ProjectMember.user_id == user.id)
            ).all()
            project_ids = [m.project_id for m in memberships]
            
            # Also include projects with no members (open to all authenticated users)
            projects = db_session.exec(select(Project).order_by(Project.name)).all()
            projects = [p for p in projects if not project_ids or p.id in project_ids]
        
        return [
            {
                "id": p.id,
                "name": p.name,
                "language": p.language,
                "description": p.description,
                "created_at": p.created_at,
            }
            for p in projects
        ]


@router.post("/projects")
async def create_project_api(
    body: ProjectCreate,
    user: User = Depends(require_auth),
    session: Session = Depends(lambda: None),
):
    """Create a new project."""
    from sqlmodel import Session
    from pvs_tracker.db import engine
    with Session(engine) as db_session:
        # Check if project name already exists
        existing = db_session.exec(select(Project).where(Project.name == body.name)).first()
        if existing:
            raise HTTPException(status_code=400, detail="Project name already exists")
        
        project = Project(
            name=body.name,
            language=body.language,
            description=body.description,
            source_root_win=body.source_root_win,
            source_root_linux=body.source_root_linux,
            quality_gate_id=body.quality_gate_id,
        )
        db_session.add(project)
        db_session.commit()
        db_session.refresh(project)
        
        # Add creator as project admin
        membership = ProjectMember(
            project_id=project.id,
            user_id=user.id,
            role=UserRole.ADMIN,
        )
        db_session.add(membership)
        db_session.commit()
        
        # Log activity
        log_activity(db_session, "create", "project", project.id, project.id, user.id)
        db_session.commit()
        
        return {"id": project.id, "name": project.name}


@router.get("/projects/{project_id}")
async def get_project_api(
    project_id: int,
    user: User = Depends(require_auth),
    session: Session = Depends(lambda: None),
):
    """Get project details."""
    from sqlmodel import Session
    from pvs_tracker.db import engine
    with Session(engine) as db_session:
        project = db_session.get(Project, project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        if not can_access_project(user, project_id):
            raise HTTPException(status_code=403, detail="Access denied")
        
        return {
            "id": project.id,
            "name": project.name,
            "language": project.language,
            "description": project.description,
            "source_root_win": project.source_root_win,
            "source_root_linux": project.source_root_linux,
            "git_url": project.git_url,
            "git_branch": project.git_branch,
            "source_archive_path": project.source_archive_path,
            "quality_gate_id": project.quality_gate_id,
            "created_at": project.created_at,
        }


@router.patch("/projects/{project_id}")
async def update_project_api(
    project_id: int,
    body: ProjectUpdate,
    user: User = Depends(require_auth),
    session: Session = Depends(lambda: None),
):
    """Update project settings."""
    from sqlmodel import Session
    from pvs_tracker.db import engine
    with Session(engine) as db_session:
        project = db_session.get(Project, project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        if not can_modify_project(user, project_id):
            raise HTTPException(status_code=403, detail="Access denied")
        
        if body.name is not None:
            project.name = body.name
        if body.language is not None:
            project.language = body.language
        if body.description is not None:
            project.description = body.description
        if body.source_root_win is not None:
            project.source_root_win = body.source_root_win if body.source_root_win else None
        if body.source_root_linux is not None:
            project.source_root_linux = body.source_root_linux if body.source_root_linux else None
        if body.git_url is not None:
            project.git_url = body.git_url if body.git_url else None
        if body.git_branch is not None:
            project.git_branch = body.git_branch
        if body.quality_gate_id is not None:
            project.quality_gate_id = body.quality_gate_id
        
        db_session.add(project)
        db_session.commit()
        
        log_activity(db_session, "update", "project", project.id, project.id, user.id)
        db_session.commit()
        
        return {"id": project.id, "name": project.name}


@router.delete("/projects/{project_id}", dependencies=[Depends(require_admin)])
async def delete_project_api(project_id: int, session: Session = Depends(lambda: None)):
    """Delete a project and all associated data (admin only)."""
    from sqlmodel import Session
    from pvs_tracker.db import engine
    with Session(engine) as db_session:
        project = db_session.get(Project, project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        # Delete all related data
        runs = db_session.exec(select(Run).where(Run.project_id == project_id)).all()
        run_ids = [run.id for run in runs if run.id is not None]
        if run_ids:
            reports = db_session.exec(select(RunReport).where(RunReport.run_id.in_(run_ids))).all()
            for report in reports:
                db_session.delete(report)

            snapshot_files = db_session.exec(
                select(CodeSnapshotFile).where(CodeSnapshotFile.run_id.in_(run_ids))
            ).all()
            for snapshot_file in snapshot_files:
                db_session.delete(snapshot_file)

            metrics = db_session.exec(select(MetricSnapshot).where(MetricSnapshot.run_id.in_(run_ids))).all()
            for metric in metrics:
                db_session.delete(metric)

        for run in runs:
            issues = db_session.exec(select(Issue).where(Issue.run_id == run.id)).all()
            for issue in issues:
                comments = db_session.exec(select(IssueComment).where(IssueComment.issue_id == issue.id)).all()
                for comment in comments:
                    db_session.delete(comment)
                db_session.delete(issue)
            db_session.delete(run)
        
        members = db_session.exec(select(ProjectMember).where(ProjectMember.project_id == project_id)).all()
        for member in members:
            db_session.delete(member)
        
        db_session.delete(project)
        db_session.commit()
        
        return {"status": "deleted", "id": project_id}


# ---------------------------------------------------------------------------
# Project Members API
# ---------------------------------------------------------------------------

@router.post("/projects/{project_id}/members")
async def add_project_member_api(
    project_id: int,
    body: ProjectMemberAdd,
    user: User = Depends(require_auth),
    session: Session = Depends(lambda: None),
):
    """Add a member to a project (project admin only)."""
    from sqlmodel import Session
    from pvs_tracker.db import engine
    with Session(engine) as db_session:
        project = db_session.get(Project, project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        # Check if user is project admin
        if not can_access_project(user, project_id, UserRole.ADMIN):
            raise HTTPException(status_code=403, detail="Access denied")
        
        # Check if user exists
        target_user = db_session.get(User, body.user_id)
        if not target_user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Check if already a member
        existing = db_session.exec(
            select(ProjectMember).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == body.user_id,
            )
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail="User is already a member")
        
        member = ProjectMember(
            project_id=project_id,
            user_id=body.user_id,
            role=body.role,
        )
        db_session.add(member)
        db_session.commit()
        
        return {"project_id": project_id, "user_id": body.user_id, "role": body.role}


@router.get("/projects/{project_id}/members")
async def list_project_members_api(
    project_id: int,
    user: User = Depends(require_auth),
    session: Session = Depends(lambda: None),
):
    """List project members."""
    from sqlmodel import Session
    from pvs_tracker.db import engine
    with Session(engine) as db_session:
        if not can_access_project(user, project_id):
            raise HTTPException(status_code=403, detail="Access denied")
        
        members = db_session.exec(
            select(ProjectMember, User)
            .join(User, ProjectMember.user_id == User.id)
            .where(ProjectMember.project_id == project_id)
        ).all()
        
        return [
            {
                "id": m[0].id,
                "user_id": m[0].user_id,
                "username": m[1].username,
                "email": m[1].email,
                "role": m[0].role,
            }
            for m in members
        ]


# ---------------------------------------------------------------------------
# Quality Gates API
# ---------------------------------------------------------------------------

@router.get("/quality-gates")
async def list_quality_gates_api(user: User = Depends(require_auth), session: Session = Depends(lambda s: None)):
    """List all quality gates."""
    from sqlmodel import Session
    from pvs_tracker.db import engine
    with Session(engine) as db_session:
        gates = db_session.exec(select(QualityGate).order_by(QualityGate.name)).all()
        return [
            {
                "id": g.id,
                "name": g.name,
                "is_default": g.is_default,
                "created_at": g.created_at,
                "conditions_count": len(g.conditions),
            }
            for g in gates
        ]


@router.post("/quality-gates")
async def create_quality_gate_api(
    body: QualityGateCreate,
    user: User = Depends(require_admin),
    session: Session = Depends(lambda s: None),
):
    """Create a new quality gate (admin only)."""
    from sqlmodel import Session
    from pvs_tracker.db import engine
    with Session(engine) as db_session:
        gate = QualityGate(name=body.name, is_default=body.is_default)
        db_session.add(gate)
        db_session.commit()
        db_session.refresh(gate)
        return {"id": gate.id, "name": gate.name}


@router.get("/quality-gates/{gate_id}")
async def get_quality_gate_api(gate_id: int, user: User = Depends(require_auth), session: Session = Depends(lambda s: None)):
    """Get quality gate details."""
    from sqlmodel import Session
    from pvs_tracker.db import engine
    with Session(engine) as db_session:
        gate = db_session.get(QualityGate, gate_id)
        if not gate:
            raise HTTPException(status_code=404, detail="Quality gate not found")
        
        conditions = db_session.exec(
            select(QualityGateCondition).where(QualityGateCondition.quality_gate_id == gate_id)
        ).all()
        
        return {
            "id": gate.id,
            "name": gate.name,
            "is_default": gate.is_default,
            "conditions": [
                {
                    "id": c.id,
                    "metric": c.metric,
                    "operator": c.operator,
                    "threshold": c.threshold,
                    "error_policy": c.error_policy,
                }
                for c in conditions
            ],
        }


@router.post("/quality-gates/{gate_id}/conditions")
async def add_quality_gate_condition_api(
    gate_id: int,
    body: QualityGateConditionCreate,
    user: User = Depends(require_admin),
    session: Session = Depends(lambda s: None),
):
    """Add a condition to a quality gate (admin only)."""
    from sqlmodel import Session
    from pvs_tracker.db import engine
    with Session(engine) as db_session:
        gate = db_session.get(QualityGate, gate_id)
        if not gate:
            raise HTTPException(status_code=404, detail="Quality gate not found")
        
        condition = QualityGateCondition(
            quality_gate_id=gate_id,
            metric=body.metric,
            operator=body.operator,
            threshold=body.threshold,
            error_policy=body.error_policy,
        )
        db_session.add(condition)
        db_session.commit()
        return {"id": condition.id, "metric": body.metric}


# ---------------------------------------------------------------------------
# Issues API
# ---------------------------------------------------------------------------

@router.get("/projects/{project_id}/issues")
async def list_issues_api(
    project_id: int,
    user: User = Depends(require_auth),
    run_id: Optional[int] = Query(None),
    severity: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    resolution: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    os_filter: Optional[str] = Query(None),   # ⬅️ новый параметр
    session: Session = Depends(lambda: None),
):
    """List issues with pagination and filters."""
    from sqlmodel import Session
    from pvs_tracker.db import engine
    with Session(engine) as db_session:
        if not can_access_project(user, project_id):
            raise HTTPException(status_code=403, detail="Access denied")
        
        # --- Выбор запуска с учётом os_filter ---
        run = None
        common_fps = set()

        if run_id:
            run = db_session.get(Run, run_id)
        elif os_filter in ("windows", "linux"):
            run = db_session.exec(
                select(Run)
                .where(Run.project_id == project_id, Run.status == "done", Run.os == os_filter)
                .order_by(Run.timestamp.desc())
                .limit(1)
            ).first()
        elif os_filter == "common":
            win_run = db_session.exec(
                select(Run)
                .where(Run.project_id == project_id, Run.status == "done", Run.os == "windows")
                .order_by(Run.timestamp.desc()).limit(1)
            ).first()
            lin_run = db_session.exec(
                select(Run)
                .where(Run.project_id == project_id, Run.status == "done", Run.os == "linux")
                .order_by(Run.timestamp.desc()).limit(1)
            ).first()
            if win_run and lin_run:
                win_fps = set(i.fingerprint for i in db_session.exec(
                    select(Issue).where(Issue.run_id == win_run.id, Issue.status.in_(["new", "existing"]))
                ).all())
                lin_fps = set(i.fingerprint for i in db_session.exec(
                    select(Issue).where(Issue.run_id == lin_run.id, Issue.status.in_(["new", "existing"]))
                ).all())
                common_fps = win_fps & lin_fps
                run = win_run
            else:
                run = None
        else:
            # all (os_filter не задан или пустой)
            run = db_session.exec(
                select(Run)
                .where(Run.project_id == project_id, Run.status == "done")
                .order_by(Run.timestamp.desc())
                .limit(1)
            ).first()
        
        if not run:
            return {"issues": [], "total": 0, "page": page, "per_page": per_page}
        
        query = select(Issue).where(Issue.run_id == run.id)
        if os_filter == "common" and common_fps:
            query = query.where(Issue.fingerprint.in_(common_fps))
        
        if severity:
            query = query.where(Issue.severity == severity)
        if status:
            query = query.where(Issue.status == status)
        if resolution:
            query = query.where(Issue.resolution == resolution)
        if q:
            like = f"%{q}%"
            query = query.where(
                (Issue.file_path.ilike(like)) |
                (Issue.rule_code.ilike(like)) |
                (Issue.message.ilike(like))
            )
        
        # Total count
        total_query = select(func.count()).select_from(Issue).where(Issue.run_id == run.id)
        if os_filter == "common" and common_fps:
            total_query = total_query.where(Issue.fingerprint.in_(common_fps))
        if severity:
            total_query = total_query.where(Issue.severity == severity)
        if status:
            total_query = total_query.where(Issue.status == status)
        if resolution:
            total_query = total_query.where(Issue.resolution == resolution)
        
        total = db_session.exec(total_query).one()
        
        issues = db_session.exec(
            query.offset((page - 1) * per_page).limit(per_page).order_by(Issue.line)
        ).all()
        
        return {
            "issues": [
                {
                    "id": i.id,
                    "fingerprint": i.fingerprint,
                    "file_path": i.file_path,
                    "line": i.line,
                    "column": i.column,
                    "rule_code": i.rule_code,
                    "severity": i.severity,
                    "message": i.message,
                    "status": i.status,
                    "resolution": i.resolution,
                    "cwe_id": i.cwe_id,
                    "technical_debt_minutes": i.technical_debt_minutes,
                    "created_at": i.created_at,
                }
                for i in issues
            ],
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": (total + per_page - 1) // per_page,
        }


@router.post("/issues/{fingerprint}/resolution")
async def update_issue_resolution_api(
    fingerprint: str,
    body: IssueResolutionUpdate,
    user: User = Depends(require_auth),
    session: Session = Depends(lambda s: None),
):
    """Update issue resolution status."""
    from sqlmodel import Session
    from pvs_tracker.db import engine
    with Session(engine) as db_session:
        issues = db_session.exec(select(Issue).where(Issue.fingerprint == fingerprint)).all()
        if not issues:
            raise HTTPException(status_code=404, detail="Issue not found")
        
        for issue in issues:
            issue.resolution = body.resolution
        
        db_session.commit()
        
        # Add comment if provided
        if body.comment:
            comment = IssueComment(
                issue_fingerprint=fingerprint,
                user_id=user.id,
                comment=body.comment,
            )
            db_session.add(comment)
            db_session.commit()
        
        return {"status": "updated", "fingerprint": fingerprint, "resolution": body.resolution}


@router.get("/issues/{issue_id}/comments")
async def list_issue_comments_api(
    issue_id: int,
    user: User = Depends(require_auth),
    session: Session = Depends(lambda s: None),
):
    """List comments on an issue."""
    from sqlmodel import Session
    from pvs_tracker.db import engine
    with Session(engine) as db_session:
        comments = db_session.exec(
            select(IssueComment, User)
            .join(User, IssueComment.user_id == User.id)
            .where(IssueComment.issue_id == issue_id)
            .order_by(IssueComment.created_at)
        ).all()
        
        return [
            {
                "id": c[0].id,
                "user": c[1].username,
                "comment": c[0].comment,
                "created_at": c[0].created_at,
                "edited_at": c[0].edited_at,
            }
            for c in comments
        ]


@router.post("/issues/{issue_id}/comments")
async def add_issue_comment_api(
    issue_id: int,
    body: IssueCommentCreate,
    user: User = Depends(require_auth),
    session: Session = Depends(lambda s: None),
):
    """Add a comment to an issue."""
    from sqlmodel import Session
    from pvs_tracker.db import engine
    with Session(engine) as db_session:
        issue = db_session.get(Issue, issue_id)
        if not issue:
            raise HTTPException(status_code=404, detail="Issue not found")
        
        comment = IssueComment(
            issue_id=issue_id,
            user_id=user.id,
            comment=body.comment,
        )
        db_session.add(comment)
        db_session.commit()
        db_session.refresh(comment)
        
        return {"id": comment.id, "comment": body.comment}


# ---------------------------------------------------------------------------
# Export API
# ---------------------------------------------------------------------------

@router.get("/projects/{project_id}/export/csv")
async def export_issues_csv_api(
    project_id: int,
    user: User = Depends(require_auth),
    run_id: Optional[int] = Query(None),
    session: Session = Depends(lambda: None),
):
    """Export issues as CSV."""
    from sqlmodel import Session
    from pvs_tracker.db import engine
    with Session(engine) as db_session:
        if not can_access_project(user, project_id):
            raise HTTPException(status_code=403, detail="Access denied")
        
        # Determine which run to export
        if run_id:
            run = db_session.get(Run, run_id)
        else:
            run = db_session.exec(
                select(Run)
                .where(Run.project_id == project_id, Run.status == "done")
                .order_by(Run.timestamp.desc())
                .limit(1)
            ).first()
        
        if not run:
            raise HTTPException(status_code=404, detail="No runs found")
        
        issues = db_session.exec(select(Issue).where(Issue.run_id == run.id)).all()
        
        # Create CSV
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "Fingerprint", "File", "Line", "Column", "Rule Code",
            "Severity", "Message", "Status", "Resolution", "CWE",
            "Technical Debt (min)", "Created At"
        ])
        
        for issue in issues:
            writer.writerow([
                issue.fingerprint,
                issue.file_path,
                issue.line,
                issue.column or "",
                issue.rule_code,
                issue.severity,
                issue.message,
                issue.status,
                issue.resolution,
                issue.cwe_id or "",
                issue.technical_debt_minutes,
                issue.created_at,
            ])
        
        output.seek(0)
        
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=issues_{project_id}_{run.id}.csv"},
        )


# ============================================================================
# Global Settings API — FIXED
# ============================================================================

@router.get("/settings/global")
async def get_global_settings_api(
    user: User = Depends(require_admin),
    session: Session = Depends(get_session),  # 🔑 ИСПРАВЛЕНО
):
    """Get global application settings (admin only)."""
    settings = session.exec(select(GlobalSettings).where(GlobalSettings.id == 1)).first()
    if not settings:
        settings = GlobalSettings()
        session.add(settings)
        session.commit()
        session.refresh(settings)
    
    return {
        "id": settings.id,
        "default_source_root_win": settings.default_source_root_win,
        "default_source_root_linux": settings.default_source_root_linux,
        "updated_at": settings.updated_at,
    }

@router.patch("/settings/global")
async def update_global_settings_api(
    body: dict,
    user: User = Depends(require_admin),
    session: Session = Depends(get_session),  # 🔑 ИСПРАВЛЕНО
):
    """Update global application settings (admin only)."""
    settings = session.exec(select(GlobalSettings).where(GlobalSettings.id == 1)).first()
    if not settings:
        settings = GlobalSettings()
        session.add(settings)
    
    if "default_source_root_win" in body:
        settings.default_source_root_win = body["default_source_root_win"] or None
    if "default_source_root_linux" in body:
        settings.default_source_root_linux = body["default_source_root_linux"] or None
    
    settings.updated_at = datetime.utcnow()
    session.commit()
    
    return {
        "id": settings.id,
        "default_source_root_win": settings.default_source_root_win,
        "default_source_root_linux": settings.default_source_root_linux,
        "updated_at": settings.updated_at,
    }


# ---------------------------------------------------------------------------
# Activity Log API
# ---------------------------------------------------------------------------

@router.get("/projects/{project_id}/activity")
async def get_project_activity_api(
    project_id: int,
    user: User = Depends(require_auth),
    limit: int = Query(50, ge=1, le=200),
    session: Session = Depends(lambda: None),
):
    """Get project activity log."""
    from sqlmodel import Session
    from pvs_tracker.db import engine
    with Session(engine) as db_session:
        if not can_access_project(user, project_id):
            raise HTTPException(status_code=403, detail="Access denied")
        
        logs = db_session.exec(
            select(ActivityLog, User)
            .join(User, ActivityLog.user_id == User.id, isouter=True)
            .where(ActivityLog.project_id == project_id)
            .order_by(ActivityLog.timestamp.desc())
            .limit(limit)
        ).all()
        
        return [
            {
                "id": log[0].id,
                "action": log[0].action,
                "entity_type": log[0].entity_type,
                "entity_id": log[0].entity_id,
                "details": log[0].details,
                "timestamp": log[0].timestamp,
                "user": log[1].username if log[1] else "system",
            }
            for log in logs
        ]
