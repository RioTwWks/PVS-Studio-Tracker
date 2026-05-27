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
    ProjectMember, QualityGate, QualityGateCondition, QualityGateRule, GlobalSettings,
    IssueComment, ActivityLog, MetricSnapshot, IssueResolution,
    RunReport, CodeSnapshotFile, UserProjectNotification, ProjectGroup
)
from pvs_tracker.auth_service import (
    require_auth,
    require_admin,
    require_role,
    create_user,
    authenticate_credentials,
    create_access_token,
    get_current_user,
    establish_session,
    get_auth_settings_public,
    can_access_project,
    can_modify_project,
)
from pvs_tracker.quality_gate import (
    evaluate_quality_gate,
    calculate_run_metrics,
    create_default_quality_gate,
    set_gate_rules,
    get_gate_rule_codes,
    populate_default_gate_rules,
)
from pvs_tracker.warnings_catalog import backfill_classifier_languages, sync_warnings_catalog
from pvs_tracker.db import get_session
from pvs_tracker.security import hash_password

router = APIRouter(prefix="/api/v2")


class ProjectGroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    display_order: int = Field(default=0)

class ProjectGroupUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    display_order: Optional[int] = None

@router.get("/admin/groups")
async def list_groups(
    _admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    groups = session.exec(select(ProjectGroup).order_by(ProjectGroup.display_order, ProjectGroup.name)).all()
    return [{"id": g.id, "name": g.name, "display_order": g.display_order} for g in groups]

@router.post("/admin/groups")
async def create_group(
    body: ProjectGroupCreate,
    _admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    existing = session.exec(select(ProjectGroup).where(ProjectGroup.name == body.name)).first()
    if existing:
        raise HTTPException(400, "Group already exists")
    group = ProjectGroup(name=body.name, display_order=body.display_order)
    session.add(group)
    session.commit()
    return {"id": group.id, "name": group.name, "display_order": group.display_order}

@router.put("/admin/groups/{group_id}")
async def update_group(
    group_id: int,
    body: ProjectGroupUpdate,
    _admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    group = session.get(ProjectGroup, group_id)
    if not group:
        raise HTTPException(404, "Group not found")
    if body.name is not None:
        group.name = body.name
    if body.display_order is not None:
        group.display_order = body.display_order
    session.add(group)
    session.commit()
    return {"id": group.id, "name": group.name, "display_order": group.display_order}

@router.delete("/admin/groups/{group_id}")
async def delete_group(
    group_id: int,
    _admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    group = session.get(ProjectGroup, group_id)
    if not group:
        raise HTTPException(404, "Group not found")
    # Проверяем, используется ли группа в проектах
    projects = session.exec(select(Project).where(Project.group_name == group.name)).all()
    if projects:
        raise HTTPException(409, f"Group is used by {len(projects)} project(s). Move them first.")
    session.delete(group)
    session.commit()
    return {"status": "deleted"}

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
    first_name: Optional[str] = Field(default=None, max_length=100)
    last_name: Optional[str] = Field(default=None, max_length=100)
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None
    password: Optional[str] = Field(default=None, min_length=6)


class ProfileUpdate(BaseModel):
    first_name: Optional[str] = Field(default=None, max_length=100)
    last_name: Optional[str] = Field(default=None, max_length=100)
    email: Optional[str] = Field(default=None, max_length=254)
    notify_api_uploads: Optional[bool] = None


class NotificationProjectsUpdate(BaseModel):
    project_ids: list[int] = Field(default_factory=list)


class LoginRequest(BaseModel):
    username: str
    password: str


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    language: str = "c++"
    description: Optional[str] = None
    source_root_win: Optional[str] = None
    source_root_linux: Optional[str] = None
    source_root_macos: Optional[str] = None
    git_url: Optional[str] = None
    git_branch: str = "main"
    quality_gate_id: Optional[int] = None
    slug: Optional[str] = None
    author_email: Optional[str] = None
    group_name: Optional[str] = None
    cvs_system: Optional[str] = None
    repo_path: Optional[str] = None
    analysis_branch: Optional[str] = None
    jira_project: Optional[str] = None
    pvs_check_conf_name: Optional[str] = None
    pvs_check_arch: Optional[str] = None
    disabled: Optional[bool] = None
    disable_jira: Optional[bool] = None


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    language: Optional[str] = None
    description: Optional[str] = None
    source_root_win: Optional[str] = None
    source_root_linux: Optional[str] = None
    source_root_macos: Optional[str] = None
    git_url: Optional[str] = None
    git_branch: Optional[str] = None
    quality_gate_id: Optional[int] = None
    slug: Optional[str] = None
    author_email: Optional[str] = None
    group_name: Optional[str] = None
    cvs_system: Optional[str] = None
    repo_path: Optional[str] = None
    analysis_branch: Optional[str] = None
    jira_project: Optional[str] = None
    pvs_check_conf_name: Optional[str] = None
    pvs_check_arch: Optional[str] = None
    disabled: Optional[bool] = None
    disable_jira: Optional[bool] = None
    last_processed_changeset: Optional[str] = None
    release_version: Optional[str] = None


class QualityGateCreate(BaseModel):
    name: str
    is_default: bool = False
    rule_codes: list[str] = Field(default_factory=list)


class QualityGateUpdate(BaseModel):
    name: Optional[str] = None
    is_default: Optional[bool] = None
    rule_codes: Optional[list[str]] = None


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


def _serialize_user_admin(user: User) -> dict:
    """Build API response for admin user list / edit."""
    role = user.role.value if hasattr(user.role, "value") else user.role
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "email": user.email,
        "role": role,
        "auth_provider": user.auth_provider,
        "is_active": user.is_active,
        "created_at": user.created_at,
        "last_login": user.last_login,
    }


def _serialize_user_profile(session: Session, user: User) -> dict:
    """Build API response for current user profile."""
    notification_rows = session.exec(
        select(UserProjectNotification.project_id).where(
            UserProjectNotification.user_id == user.id,
        )
    ).all()
    notification_project_ids = [row for row in notification_rows]
    data = _serialize_user_admin(user)
    data["notify_api_uploads"] = user.notify_api_uploads
    data["notification_project_ids"] = notification_project_ids
    return data


# ---------------------------------------------------------------------------
# Authentication & User Management API
# ---------------------------------------------------------------------------

@router.post("/auth/login")
async def api_login(body: LoginRequest, request: Request):
    """Authenticate user and return JWT token (also sets session cookie)."""
    from sqlmodel import Session
    from pvs_tracker.db import engine

    with Session(engine) as db_session:
        user = authenticate_credentials(db_session, body.username, body.password)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid credentials")

        establish_session(request, user)
        token = create_access_token(data={"sub": str(user.id), "username": user.username})
        role = user.role.value if hasattr(user.role, "value") else user.role
        return {
            "access_token": token,
            "token_type": "bearer",
            "user": {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "role": role,
            },
        }


@router.get("/users/me")
async def get_me(
    user: User = Depends(require_auth),
    session: Session = Depends(get_session),
):
    """Get current user profile."""
    db_user = session.get(User, user.id)
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
    return _serialize_user_profile(session, db_user)


@router.patch("/users/me")
async def update_me(
    body: ProfileUpdate,
    user: User = Depends(require_auth),
    session: Session = Depends(get_session),
):
    """Update current user profile fields."""
    db_user = session.get(User, user.id)
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")

    if body.first_name is not None:
        db_user.first_name = body.first_name or None
    if body.last_name is not None:
        db_user.last_name = body.last_name or None
    if body.email is not None:
        db_user.email = body.email.strip() if body.email and body.email.strip() else None
    if body.notify_api_uploads is not None:
        db_user.notify_api_uploads = body.notify_api_uploads

    session.add(db_user)
    session.commit()
    session.refresh(db_user)
    return _serialize_user_profile(session, db_user)


@router.get("/users/me/notifications")
async def get_my_notifications(
    user: User = Depends(require_auth),
    session: Session = Depends(get_session),
):
    """Get API upload notification subscription settings."""
    rows = session.exec(
        select(UserProjectNotification.project_id).where(
            UserProjectNotification.user_id == user.id,
        )
    ).all()
    db_user = session.get(User, user.id)
    enabled = db_user.notify_api_uploads if db_user else False
    return {"enabled": enabled, "project_ids": list(rows)}


@router.put("/users/me/notifications")
async def update_my_notifications(
    body: NotificationProjectsUpdate,
    user: User = Depends(require_auth),
    session: Session = Depends(get_session),
):
    """Replace project subscriptions for API upload email notifications."""
    for project_id in body.project_ids:
        if not session.get(Project, project_id):
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
        members = session.exec(
            select(ProjectMember).where(ProjectMember.project_id == project_id)
        ).all()
        if members:
            if not any(m.user_id == user.id for m in members):
                raise HTTPException(
                    status_code=403,
                    detail=f"No access to project {project_id}",
                )
        elif not can_access_project(user, project_id):
            raise HTTPException(
                status_code=403,
                detail=f"No access to project {project_id}",
            )

    existing = session.exec(
        select(UserProjectNotification).where(UserProjectNotification.user_id == user.id)
    ).all()
    for row in existing:
        session.delete(row)

    for project_id in body.project_ids:
        session.add(UserProjectNotification(user_id=user.id, project_id=project_id))

    session.commit()
    db_user = session.get(User, user.id)
    enabled = db_user.notify_api_uploads if db_user else False
    return {"enabled": enabled, "project_ids": body.project_ids}


@router.get("/users")
async def list_users(
    _admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    """List all users (admin only)."""
    users = session.exec(select(User).order_by(User.username)).all()
    return [_serialize_user_admin(u) for u in users]


@router.post("/users")
async def create_user_api(
    body: UserCreate,
    _admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    """Create a new local user (admin only)."""
    existing = session.exec(select(User).where(User.username == body.username.strip())).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username already exists")

    user = create_user(session, body.username, body.password, body.email, body.role)
    return _serialize_user_admin(user)


@router.patch("/users/{user_id}")
async def update_user_api(
    user_id: int,
    body: UserUpdate,
    _admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    """Update user (admin only)."""
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if body.email is not None:
        user.email = body.email.strip() if body.email and body.email.strip() else None
    if body.first_name is not None:
        user.first_name = body.first_name or None
    if body.last_name is not None:
        user.last_name = body.last_name or None
    if body.role is not None:
        user.role = body.role
    if body.is_active is not None:
        user.is_active = body.is_active
    if body.password is not None:
        if user.auth_provider != "local":
            raise HTTPException(
                status_code=400,
                detail="Password can only be set for local accounts",
            )
        user.password_hash = hash_password(body.password)

    session.add(user)
    session.commit()
    session.refresh(user)
    return _serialize_user_admin(user)


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
        
        from pvs_tracker.project_ci import slug_from_name

        payload = body.model_dump(exclude_unset=True)
        if not payload.get("slug"):
            payload["slug"] = slug_from_name(body.name)
        project = Project(**payload)
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
            "source_root_macos": project.source_root_macos,
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

        empty_to_none = ("source_root_win", "source_root_linux", "source_root_macos", "git_url")
        for key, value in body.model_dump(exclude_unset=True).items():
            if key in empty_to_none and value == "":
                value = None
            setattr(project, key, value)

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
# PVS Warnings catalog API
# ---------------------------------------------------------------------------

@router.get("/warnings")
async def list_warnings_api(
    user: User = Depends(require_auth),
    q: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    language: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=500),
    session: Session = Depends(get_session),
):
    """List PVS warning catalog with pagination."""
    filters = []
    if q:
        like = f"%{q}%"
        filters.append(
            (ErrorClassifier.rule_code.ilike(like)) | (ErrorClassifier.name.ilike(like))
        )
    if category:
        filters.append(ErrorClassifier.category.ilike(f"%{category}%"))
    if language:
        filters.append(ErrorClassifier.language == language)

    count_stmt = select(func.count(ErrorClassifier.id))
    list_stmt = select(ErrorClassifier)
    for clause in filters:
        count_stmt = count_stmt.where(clause)
        list_stmt = list_stmt.where(clause)

    total = session.exec(count_stmt).one()
    rows = session.exec(
        list_stmt.order_by(ErrorClassifier.rule_code)
        .offset((page - 1) * per_page)
        .limit(per_page)
    ).all()

    last_sync = session.exec(
        select(func.max(ErrorClassifier.synced_at))
    ).one()

    return {
        "warnings": [
            {
                "rule_code": w.rule_code,
                "name": w.name,
                "type": w.type,
                "priority": w.priority,
                "category": w.category,
                "language": w.language,
                "doc_url": w.doc_url,
            }
            for w in rows
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
        "last_synced_at": last_sync,
    }


@router.post("/warnings/sync")
async def sync_warnings_api(
    user: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    """Import/update warning catalog from pvs-studio.com (admin only)."""
    try:
        result = sync_warnings_catalog(session)
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Sync failed: {exc}") from exc

    default_gate = session.exec(
        select(QualityGate).where(QualityGate.is_default == True)  # noqa: E712
    ).first()
    if default_gate and default_gate.id is not None:
        populate_default_gate_rules(session, default_gate.id)
        result["default_gate_rules"] = len(get_gate_rule_codes(session, default_gate.id))

    return result


@router.post("/warnings/backfill-languages")
async def backfill_warning_languages_api(
    user: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    """Backfill language tags from rule codes (admin only)."""
    count = backfill_classifier_languages(session)
    return {"languages_backfilled": count}


def _gate_rule_codes(session: Session, gate_id: int) -> list[str]:
    return sorted(get_gate_rule_codes(session, gate_id))


def _clear_default_flag(session: Session, except_gate_id: Optional[int] = None) -> None:
    gates = session.exec(select(QualityGate).where(QualityGate.is_default == True)).all()  # noqa: E712
    for gate in gates:
        if except_gate_id is None or gate.id != except_gate_id:
            gate.is_default = False
            session.add(gate)
    session.commit()


# ---------------------------------------------------------------------------
# Quality Gates API
# ---------------------------------------------------------------------------

@router.get("/quality-gates")
async def list_quality_gates_api(
    user: User = Depends(require_auth),
    session: Session = Depends(get_session),
):
    """List all quality gates."""
    gates = session.exec(select(QualityGate).order_by(QualityGate.name)).all()
    result = []
    for g in gates:
        rules_count = 0
        if g.id is not None:
            rules_count = len(get_gate_rule_codes(session, g.id))
        projects_count = session.exec(
            select(func.count()).where(Project.quality_gate_id == g.id)
        ).one()
        result.append(
            {
                "id": g.id,
                "name": g.name,
                "is_default": g.is_default,
                "created_at": g.created_at,
                "rules_count": rules_count,
                "projects_count": projects_count,
            }
        )
    return result


@router.post("/quality-gates")
async def create_quality_gate_api(
    body: QualityGateCreate,
    user: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    """Create a new quality gate (admin only)."""
    existing = session.exec(select(QualityGate).where(QualityGate.name == body.name)).first()
    if existing:
        raise HTTPException(status_code=400, detail="Quality gate name already exists")

    if body.is_default:
        _clear_default_flag(session)

    gate = QualityGate(name=body.name, is_default=body.is_default)
    session.add(gate)
    session.commit()
    session.refresh(gate)

    if gate.id is not None and body.rule_codes:
        set_gate_rules(session, gate.id, body.rule_codes)

    return {
        "id": gate.id,
        "name": gate.name,
        "rule_codes": _gate_rule_codes(session, gate.id) if gate.id else [],
    }


@router.get("/quality-gates/{gate_id}")
async def get_quality_gate_api(
    gate_id: int,
    user: User = Depends(require_auth),
    session: Session = Depends(get_session),
):
    """Get quality gate details."""
    gate = session.get(QualityGate, gate_id)
    if not gate:
        raise HTTPException(status_code=404, detail="Quality gate not found")

    return {
        "id": gate.id,
        "name": gate.name,
        "is_default": gate.is_default,
        "rule_codes": _gate_rule_codes(session, gate_id),
        "rules_count": len(_gate_rule_codes(session, gate_id)),
    }


@router.put("/quality-gates/{gate_id}")
async def update_quality_gate_api(
    gate_id: int,
    body: QualityGateUpdate,
    user: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    """Update quality gate (admin only)."""
    gate = session.get(QualityGate, gate_id)
    if not gate:
        raise HTTPException(status_code=404, detail="Quality gate not found")

    if body.name is not None:
        other = session.exec(
            select(QualityGate).where(
                QualityGate.name == body.name,
                QualityGate.id != gate_id,
            )
        ).first()
        if other:
            raise HTTPException(status_code=400, detail="Quality gate name already exists")
        gate.name = body.name

    if body.is_default is True:
        _clear_default_flag(session, except_gate_id=gate_id)
        gate.is_default = True
    elif body.is_default is False and gate.is_default:
        others = session.exec(
            select(QualityGate).where(QualityGate.id != gate_id)
        ).all()
        if not others:
            raise HTTPException(status_code=400, detail="Cannot unset the only default gate")
        gate.is_default = False

    if body.rule_codes is not None:
        set_gate_rules(session, gate_id, body.rule_codes)

    gate.updated_at = datetime.utcnow()
    session.add(gate)
    session.commit()

    return {
        "id": gate.id,
        "name": gate.name,
        "is_default": gate.is_default,
        "rule_codes": _gate_rule_codes(session, gate_id),
    }


@router.delete("/quality-gates/{gate_id}")
async def delete_quality_gate_api(
    gate_id: int,
    user: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    """Delete quality gate (admin only)."""
    gate = session.get(QualityGate, gate_id)
    if not gate:
        raise HTTPException(status_code=404, detail="Quality gate not found")

    in_use = session.exec(
        select(func.count()).where(Project.quality_gate_id == gate_id)
    ).one()
    if in_use:
        raise HTTPException(
            status_code=409,
            detail=f"Quality gate is assigned to {in_use} project(s)",
        )

    if gate.is_default:
        raise HTTPException(status_code=400, detail="Cannot delete the default quality gate")

    rules = session.exec(
        select(QualityGateRule).where(QualityGateRule.quality_gate_id == gate_id)
    ).all()
    for rule in rules:
        session.delete(rule)

    session.delete(gate)
    session.commit()
    return {"status": "deleted", "id": gate_id}


@router.post("/quality-gates/{gate_id}/conditions")
async def add_quality_gate_condition_api(
    gate_id: int,
    body: QualityGateConditionCreate,
    user: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    """Deprecated: metric conditions are not used for gate evaluation."""
    gate = session.get(QualityGate, gate_id)
    if not gate:
        raise HTTPException(status_code=404, detail="Quality gate not found")

    condition = QualityGateCondition(
        quality_gate_id=gate_id,
        metric=body.metric,
        operator=body.operator,
        threshold=body.threshold,
        error_policy=body.error_policy,
    )
    session.add(condition)
    session.commit()
    return {"id": condition.id, "metric": body.metric, "deprecated": True}


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
    session: Session = Depends(lambda: None),
):
    """List issues with pagination and filters."""
    from sqlmodel import Session
    from pvs_tracker.db import engine
    with Session(engine) as db_session:
        if not can_access_project(user, project_id):
            raise HTTPException(status_code=403, detail="Access denied")
        
        # Determine which run to query
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
            return {"issues": [], "total": 0, "page": page, "per_page": per_page}
        
        query = select(Issue).where(Issue.run_id == run.id)
        
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
        
        # Get total count
        total_query = select(func.count()).select_from(Issue).where(Issue.run_id == run.id)
        if severity:
            total_query = total_query.where(Issue.severity == severity)
        if status:
            total_query = total_query.where(Issue.status == status)
        if resolution:
            total_query = total_query.where(Issue.resolution == resolution)
        
        total = db_session.exec(total_query).one()
        
        # Get paginated results
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
                    "author_name": i.author_name,
                    "author_email": i.author_email,
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
# Auth / Global Settings API
# ============================================================================

@router.get("/settings/auth")
async def get_auth_settings_api(_admin: User = Depends(require_admin)):
    """Read-only authentication configuration (admin only)."""
    return get_auth_settings_public()


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
        "default_source_root_macos": settings.default_source_root_macos,
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
    if "default_source_root_macos" in body:
        settings.default_source_root_macos = body["default_source_root_macos"] or None

    settings.updated_at = datetime.utcnow()
    session.commit()

    return {
        "id": settings.id,
        "default_source_root_win": settings.default_source_root_win,
        "default_source_root_linux": settings.default_source_root_linux,
        "default_source_root_macos": settings.default_source_root_macos,
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
