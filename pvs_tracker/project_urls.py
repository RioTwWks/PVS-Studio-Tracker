"""UI URL helpers: /ui/projects/{project_key}/... uses Project.slug."""

from __future__ import annotations

from urllib.parse import urlencode

from fastapi import HTTPException
from sqlmodel import Session

from sqlmodel import select

from pvs_tracker.models import Project
from pvs_tracker.project_ci import ensure_project_slug, get_project_by_slug, slug_from_name


def project_key(project: Project) -> str:
    """URL segment for a project (stored slug or derived from name)."""
    if project.slug and str(project.slug).strip():
        return str(project.slug).strip()
    return slug_from_name(project.name)


def project_ui_path(project: Project, suffix: str = "", **query: str) -> str:
    """Build /ui/projects/{key}/... path with optional query string."""
    base = f"/ui/projects/{project_key(project)}"
    if suffix:
        base = f"{base}/{suffix.lstrip('/')}"
    if query:
        qs = urlencode({k: v for k, v in query.items() if v is not None and v != ""})
        if qs:
            base = f"{base}?{qs}"
    return base


def require_project_by_key(session: Session, key: str) -> Project:
    """Resolve project by slug; 404 if not found."""
    key = key.strip()
    project = get_project_by_slug(session, key)
    if project:
        return project
    for candidate in session.exec(select(Project).where(Project.slug.is_(None))).all():
        if slug_from_name(candidate.name) == key:
            ensure_project_slug(session, candidate)
            return candidate
    raise HTTPException(status_code=404, detail="Project not found")


def register_project_url_globals(jinja_env) -> None:
    jinja_env.globals["project_key"] = project_key
    jinja_env.globals["project_ui_path"] = project_ui_path
