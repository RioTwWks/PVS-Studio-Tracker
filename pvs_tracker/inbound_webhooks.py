"""Inbound TFS/Git webhooks → Jenkins builds."""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel
from sqlmodel import Session

from pvs_tracker.ci_config import ci_settings
from pvs_tracker.db import engine
from pvs_tracker.jenkins_service import trigger_jenkins_build
from pvs_tracker.models import Project
from pvs_tracker.project_ci import (
    duplicate_release_project,
    get_project_by_name,
    get_projects_by_repo_branch,
    project_analysis_branch,
    project_repo_path,
    update_last_changeset,
)
from pvs_tracker.repository_service import (
    check_git_changes,
    check_tfvc_changes,
    check_tfvc_merge,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["ci-webhooks"])
security = HTTPBasic()


class RepoContext(BaseModel):
    type: str
    name: str
    proj: str
    group: str


def authenticate(credentials: HTTPBasicCredentials = Depends(security)) -> str:
    if (
        credentials.username != ci_settings.WEBHOOK_USERNAME
        or credentials.password != ci_settings.WEBHOOK_PASSWORD
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


def get_repo_context(request: Request) -> RepoContext:
    return RepoContext(
        type=request.headers.get("X-TFS-Repo-Type", "Unknown"),
        name=request.headers.get("X-TFS-Repo-Name", "Unnamed"),
        proj=request.headers.get("X-TFS-Proj-Name", "Unproj"),
        group=request.headers.get("X-TFS-Group-Name", "Ungroup"),
    )


def _extract_commit_id(push_data: dict[str, Any]) -> str:
    commits = push_data.get("commits")
    if isinstance(commits, list) and commits:
        return commits[0].get("commitId") or commits[0].get("id", "Unknown")
    ref_updates = push_data.get("refUpdates", [])
    if ref_updates:
        return ref_updates[0].get("newObjectId", "Unknown")
    return "Unknown"


def _trigger_and_update(session: Session, project: Project, commit_id: str, first_scan: str, linux: bool, files: list[str]) -> None:
    if project.disabled:
        logger.warning("Skipping disabled project %s", project.name)
        return
    build_id = trigger_jenkins_build(project, commit_id, first_scan, linux, files)
    from pvs_tracker.project_ci import set_analysis_queued

    set_analysis_queued(session, project, build_id)
    update_last_changeset(session, project, commit_id)


def process_tfvc_event(payload: dict[str, Any], repo_ctx: RepoContext) -> None:
    with Session(engine) as session:
        try:
            changeset = payload.get("resource", {})
            changeset_id = str(changeset.get("changesetId", ""))
            repo_name = repo_ctx.name.replace("%20", " ")
            match = re.match(r"([^/]+/[^/]+)/(.*)", repo_name)
            if not match:
                logger.error("Invalid TFVC repo_name: %s", repo_name)
                return
            repo_name_parts = list(match.groups())
            projects = get_projects_by_repo_branch(session, repo_name_parts[0], repo_name_parts[1])
            for project in projects:
                if project.cvs_system != "TFVC":
                    continue
                expected = f"{project_repo_path(project)}/{project_analysis_branch(project)}"
                if expected != repo_name:
                    if project_repo_path(project) != repo_name.split("/")[0]:
                        continue
                    path_change = check_tfvc_merge(int(changeset_id))
                    if not path_change:
                        continue
                    branch = path_change.split("/", 2)[2] if project_analysis_branch(project).count("/") == 0 else repo_name.split("/", 1)[1]
                    suffix = branch.split("/")[-1]
                    new_project = duplicate_release_project(session, project, branch, suffix)
                    _trigger_and_update(session, new_project, changeset_id, "YES", True, ["1"])
                    return
                modified_files, first_scan, comp, cmake = check_tfvc_changes(
                    project, project.last_processed_changeset or "", changeset_id
                )
                if not modified_files:
                    return
                linux = comp or cmake
                _trigger_and_update(session, project, changeset_id, first_scan, linux, modified_files)
                return
        except Exception as e:
            logger.error("TFVC event error: %s", e, exc_info=True)


def process_git_event(payload: dict[str, Any], repo_ctx: RepoContext) -> None:
    with Session(engine) as session:
        try:
            push_data = payload.get("resource", {})
            push_id = _extract_commit_id(push_data)
            repo_name = push_data.get("repository", {}).get("name", "Unknown")
            repo_proj = push_data.get("repository", {}).get("project", {}).get("name", "Unknown")
            branch = "Unknown"
            ref_updates = push_data.get("refUpdates", [])
            if ref_updates:
                branch = ref_updates[0].get("name", "Unknown").replace("refs/heads/", "")
            try:
                repo_name = repo_ctx.name.replace("%20", " ")
                repo_proj = repo_ctx.proj.replace("%20", " ")
            except AttributeError:
                pass
            if push_id == "0000000000000000000000000000000000000000":
                return
            project = get_project_by_name(session, f"{repo_proj}_{branch.split('/')[-1]}")
            if not project:
                project = get_project_by_name(session, repo_proj)
            if not project:
                logger.error("Project not found: %s", repo_proj)
                return
            if project.disabled:
                return
            analysis_branch = project_analysis_branch(project)
            if analysis_branch == branch:
                modified_files, first_scan, comp, cmake = check_git_changes(
                    project, project.last_processed_changeset or "", push_id
                )
                if not modified_files:
                    return
                _trigger_and_update(session, project, push_id, first_scan, comp or cmake, modified_files)
            elif "release" in branch:
                modified_files, first_scan, comp, cmake = check_git_changes(
                    project, project.last_processed_changeset or "", push_id
                )
                if not modified_files:
                    return
                suffix = branch.split("/")[-1]
                new_project = duplicate_release_project(session, project, branch, suffix)
                _trigger_and_update(session, new_project, push_id, "YES", True, modified_files)
        except Exception as e:
            logger.error("Git event error: %s", e, exc_info=True)


@router.post("/webhook/inbound")
async def handle_inbound_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    _username: str = Depends(authenticate),
    repo_ctx: RepoContext = Depends(get_repo_context),
) -> dict[str, str]:
    try:
        payload_data = await request.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail="Invalid JSON") from e

    if repo_ctx.type == "TFVC":
        background_tasks.add_task(process_tfvc_event, payload_data, repo_ctx)
    elif repo_ctx.type == "Git":
        background_tasks.add_task(process_git_event, payload_data, repo_ctx)
    else:
        logger.warning("Unsupported repo type: %s", repo_ctx.type)

    return {
        "status": "accepted",
        "repo_type": repo_ctx.type,
        "repo_name": repo_ctx.name,
        "event_type": str(payload_data.get("eventType", "unknown")),
    }


@router.get("/webhook/inbound/health")
def inbound_webhook_health() -> dict[str, str]:
    return {"status": "ok", "service": "pvs-tracker-inbound-webhook"}
