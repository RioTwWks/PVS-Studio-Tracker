"""UI: форма проекта (Sonar-поля) и вкладка «Анализ» на дашборде."""

from __future__ import annotations

import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from urllib.parse import quote
from fastapi.templating import Jinja2Templates
from sqlmodel import Session

from pvs_tracker.admin_utils import is_admin
from pvs_tracker.auth_service import get_current_user
from pvs_tracker.ci_activity_log import fetch_ci_activity_logs, log_ci_action
from pvs_tracker.db import get_session
from pvs_tracker.jenkins_service import trigger_jenkins_build
from pvs_tracker.models import Project, User
from pvs_tracker.project_ci import (
    create_ci_project,
    parse_sonar_form_fields,
    set_analysis_queued,
)
from pvs_tracker.project_form_context import project_form_context
from pvs_tracker.project_groups import get_group_choices, get_group_id_by_name
from pvs_tracker.project_urls import (
    project_ui_path,
    register_project_url_globals,
    require_project_by_key,
)
from pvs_tracker.repository_service import get_head_commit_git, get_latest_changeset_tfvc

logger = logging.getLogger(__name__)

import os

BASE_DIR = os.path.dirname(__file__)
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
register_project_url_globals(templates.env)
router = APIRouter(tags=["project-manage"])


def _require_auth(request: Request) -> User:
    user = get_current_user(request, None)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def _checkbox(value: Optional[str]) -> bool:
    return value in ("true", "on", "1", True)


def _template_ctx(request: Request, ctx: dict) -> dict:
    out = dict(ctx)
    out["current_user"] = get_current_user(request, None)
    return out


def _ci_panel_response(
    request: Request,
    project: Project,
    session: Session,
    *,
    active_branch: str = "",
    ci_toast_key: Optional[str] = None,
    ci_toast_type: str = "success",
    ci_toast_url: Optional[str] = None,
    ci_toast_link_text: Optional[str] = None,
) -> HTMLResponse:
    ctx = project_form_context(project, edit=True, edit_id=project.id, load_jira=False)
    ctx["group_choices"] = get_group_choices(session)
    ctx["group_id"] = get_group_id_by_name(session, project.group_name or "Ungrouped")
    ctx["project"] = project
    ctx["is_admin"] = is_admin(request)
    ctx["active_branch"] = active_branch or (
        (project.git_branch or project.analysis_branch or "").strip()
    )
    ctx["ci_toast_key"] = ci_toast_key
    ctx["ci_toast_type"] = ci_toast_type
    ctx["ci_toast_url"] = ci_toast_url
    ctx["ci_toast_link_text"] = ci_toast_link_text
    ctx["ci_activity_logs"] = fetch_ci_activity_logs(session, project.id)
    headers: dict[str, str] = {}
    if ci_toast_key or ci_toast_url:
        payload: dict[str, str] = {"type": ci_toast_type}
        if ci_toast_key:
            payload["key"] = ci_toast_key
        if ci_toast_url:
            payload["url"] = ci_toast_url
        if ci_toast_link_text:
            payload["linkText"] = ci_toast_link_text
        headers["HX-Trigger"] = json.dumps({"ciToast": payload})
    return templates.TemplateResponse(
        request, "dashboard/_ci_panel.html", ctx, headers=headers
    )


def _dashboard_settings_redirect(
    project: Project,
    *,
    settings_tab: str = "params",
    ci_error: Optional[str] = None,
) -> RedirectResponse:
    url = project_ui_path(
        project,
        "dashboard",
        tab="settings",
        settings_tab=settings_tab,
    )
    branch = (project.git_branch or project.analysis_branch or "").strip()
    if branch:
        url += f"&branch={quote(branch)}"
    if ci_error:
        url += f"&ci_error={quote(ci_error)}"
    return RedirectResponse(url=url, status_code=303)


@router.get("/ui/projects/manage")
def projects_manage_redirect() -> RedirectResponse:
    return RedirectResponse(url="/", status_code=303)


@router.get("/ui/projects/new", response_class=HTMLResponse)
def project_new_form(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    _require_auth(request)
    ctx = project_form_context(None)
    ctx["group_choices"] = get_group_choices(session)
    from pvs_tracker.project_groups import get_group_id_by_name
    ctx["group_id"] = get_group_id_by_name(session, "Ungrouped")  # по умолчанию
    ctx["form_action"] = "/ui/projects/create"
    return templates.TemplateResponse(
        request, "projects/project_form.html", _template_ctx(request, ctx)
    )


@router.get("/ui/projects/{project_key}/edit", response_class=HTMLResponse)
def project_edit_form(
    request: Request, project_key: str, session: Session = Depends(get_session)
) -> HTMLResponse:
    project = require_project_by_key(session, project_key)
    ctx = project_form_context(project, edit=True, edit_id=project.id, load_jira=False)
    
    # Передаём динамический список групп
    from pvs_tracker.project_groups import get_group_choices, get_group_id_by_name
    ctx["group_choices"] = get_group_choices(session)
    ctx["group_id"] = get_group_id_by_name(session, project.group_name or "Ungrouped")
    ctx["form_action"] = project_ui_path(project, "ci")
    
    return templates.TemplateResponse(
        request, "projects/project_form.html", _template_ctx(request, ctx)
    )


@router.get("/ui/projects/{project_key}/clone", response_class=HTMLResponse)
def project_clone_form(
    request: Request, project_key: str, session: Session = Depends(get_session)
) -> HTMLResponse:
    project = require_project_by_key(session, project_key)
    ctx = project_form_context(project, clone=True)
    ctx["group_choices"] = get_group_choices(session)
    ctx["group_id"] = get_group_id_by_name(session, project.group_name or "Ungrouped")
    ctx["form_action"] = "/ui/projects/create"
    return templates.TemplateResponse(
        request, "projects/project_form.html", _template_ctx(request, ctx)
    )


@router.post("/ui/projects/create", response_class=HTMLResponse)
async def project_create_submit(
    request: Request,
    session: Session = Depends(get_session),
    group_id: str = Form(...),
    author_email: str = Form(...),
    sonar_project_name: str = Form(...),
    sonar_project_key: str = Form(...),
    jira_project: str = Form(""),
    cvs_system: str = Form(...),
    tfs_path: str = Form(...),
    another_branch: str = Form(...),
    sub_modules: Optional[str] = Form(None),
    life_time: str = Form(""),
    cmake_msbuild: str = Form("CMake"),
    select_vcxproj: str = Form(""),
    pvs_exclude_vcxproj: str = Form(""),
    pvs_exclude_path: str = Form(""),
    pvs_check_conf_name: str = Form(...),
    pvs_check_arch: str = Form(...),
    cmake_win_commands: str = Form(...),
    cmake_linux_commands: str = Form(""),
    disabled: Optional[str] = Form(None),
    disable_jira: str = Form("true"),
) -> RedirectResponse:
    _require_auth(request)
    try:
        data = parse_sonar_form_fields(
            session=session,   # <--- передаём session
            group_id=group_id,
            author_email=author_email,
            sonar_project_name=sonar_project_name,
            sonar_project_key=sonar_project_key,
            jira_project=jira_project,
            cvs_system=cvs_system,
            tfs_path=tfs_path,
            another_branch=another_branch,
            sub_modules=_checkbox(sub_modules),
            life_time=life_time,
            cmake_msbuild=cmake_msbuild,
            select_vcxproj=select_vcxproj,
            pvs_exclude_vcxproj=pvs_exclude_vcxproj,
            pvs_exclude_path=pvs_exclude_path,
            pvs_check_conf_name=pvs_check_conf_name,
            pvs_check_arch=pvs_check_arch,
            cmake_win_commands=cmake_win_commands,
            cmake_linux_commands=cmake_linux_commands,
            disabled=_checkbox(disabled),
            disable_jira=disable_jira.lower() == "true",
        )
        project = create_ci_project(session, data)
    except ValueError as e:
        ctx = project_form_context(None)
        ctx["group_choices"] = get_group_choices(session)   # <--- динамический список
        ctx["form_action"] = "/ui/projects/create"
        ctx["error"] = str(e)
        return templates.TemplateResponse(
            request,
            "projects/project_form.html",
            _template_ctx(request, ctx),
            status_code=400,
        )
    return RedirectResponse(
        url=project_ui_path(project, "dashboard", tab="ci"),
        status_code=303,
    )


@router.post("/ui/projects/{project_key}/ci", response_class=HTMLResponse)
async def project_ci_update(
    request: Request,
    project_key: str,
    session: Session = Depends(get_session),
    group_id: str = Form(...),
    author_email: str = Form(...),
    sonar_project_name: str = Form(...),
    sonar_project_key: str = Form(...),
    jira_project: str = Form(""),
    cvs_system: str = Form(...),
    tfs_path: str = Form(...),
    sub_modules: Optional[str] = Form(None),
    life_time: str = Form(""),
    cmake_msbuild: str = Form("CMake"),
    select_vcxproj: str = Form(""),
    pvs_exclude_vcxproj: str = Form(""),
    pvs_exclude_path: str = Form(""),
    pvs_check_conf_name: str = Form(...),
    pvs_check_arch: str = Form(...),
    cmake_win_commands: str = Form(""),
    cmake_linux_commands: str = Form(""),
    disabled: Optional[str] = Form(None),
    disable_jira: str = Form("true"),
) -> RedirectResponse:
    project = require_project_by_key(session, project_key)
    try:
        data = parse_sonar_form_fields(
            session=session,   # <--- передаём session
            group_id=group_id,
            author_email=author_email,
            sonar_project_name=sonar_project_name,
            sonar_project_key=sonar_project_key,
            jira_project=jira_project,
            cvs_system=cvs_system,
            tfs_path=tfs_path,
            another_branch=project.analysis_branch or project.git_branch or "",  # сохраняем существующую ветку
            include_branch=False,   # не перезаписываем git_branch/analysis_branch
            sub_modules=_checkbox(sub_modules),
            life_time=life_time,
            cmake_msbuild=cmake_msbuild,
            select_vcxproj=select_vcxproj,
            pvs_exclude_vcxproj=pvs_exclude_vcxproj,
            pvs_exclude_path=pvs_exclude_path,
            pvs_check_conf_name=pvs_check_conf_name,
            pvs_check_arch=pvs_check_arch,
            cmake_win_commands=cmake_win_commands,
            cmake_linux_commands=cmake_linux_commands,
            disabled=_checkbox(disabled),
            disable_jira=disable_jira.lower() == "true",
        )
        from pvs_tracker.project_ci import get_project_by_name, get_project_by_slug

        if data["name"] != project.name:
            existing = get_project_by_name(session, data["name"])
            if existing and existing.id != project.id:
                raise ValueError(f"Проект {data['name']} уже существует")
        if data["slug"] != project.slug:
            existing_slug = get_project_by_slug(session, data["slug"])
            if existing_slug and existing_slug.id != project.id:
                raise ValueError(f"Ключ {data['slug']} уже занят")
        for key, val in data.items():
            setattr(project, key, val)
        session.add(project)
        session.commit()
        session.refresh(project)
    except ValueError as e:
        return _dashboard_settings_redirect(project, settings_tab="params", ci_error=str(e))
    return _dashboard_settings_redirect(project, settings_tab="params")


@router.post("/ui/projects/{project_key}/toggle-disabled", response_class=HTMLResponse)
def toggle_disabled(
    request: Request, project_key: str, session: Session = Depends(get_session)
) -> HTMLResponse:
    project = require_project_by_key(session, project_key)
    project.disabled = not project.disabled
    session.add(project)
    action = "ci_disable" if project.disabled else "ci_enable"
    log_ci_action(session, request, project, action)
    session.commit()
    session.refresh(project)
    toast_key = "ci_toast_enabled" if not project.disabled else "ci_toast_disabled"
    return _ci_panel_response(request, project, session, ci_toast_key=toast_key)


@router.post("/ui/projects/{project_key}/toggle-jira", response_class=HTMLResponse)
def toggle_jira(
    request: Request, project_key: str, session: Session = Depends(get_session)
) -> HTMLResponse:
    project = require_project_by_key(session, project_key)
    project.disable_jira = not project.disable_jira
    session.add(project)
    action = "ci_jira_pause" if project.disable_jira else "ci_jira_on"
    log_ci_action(session, request, project, action)
    session.commit()
    session.refresh(project)
    toast_key = "ci_toast_jira_on" if not project.disable_jira else "ci_toast_jira_paused"
    return _ci_panel_response(request, project, session, ci_toast_key=toast_key)


@router.post("/ui/projects/{project_key}/trigger-analysis", response_class=HTMLResponse)
def trigger_analysis(
    request: Request,
    project_key: str,
    session: Session = Depends(get_session),
    branch: str = Form(""),
) -> HTMLResponse:
    if not is_admin(request):
        raise HTTPException(status_code=403, detail="Admin only")
    project = require_project_by_key(session, project_key)
    from pvs_tracker.dashboard_context import sync_project_branch
    from pvs_tracker.project_ci import project_analysis_branch

    active_branch = (branch or project_analysis_branch(project)).strip() or "main"
    sync_project_branch(session, project, active_branch)
    session.refresh(project)
    has_cs = bool(project.last_processed_changeset and project.last_processed_changeset.strip())
    first_scan = "YES" if not has_cs else "NO"
    if has_cs:
        commit_id = project.last_processed_changeset.strip()
    elif project.cvs_system == "Git":
        commit_id = get_head_commit_git(project)
    elif project.cvs_system == "TFVC":
        commit_id = get_latest_changeset_tfvc(project)
    else:
        raise HTTPException(status_code=400, detail="Unsupported CVS")
    if not commit_id:
        raise HTTPException(status_code=500, detail="Could not resolve commit/changeset")
    trigger = trigger_jenkins_build(project, commit_id, first_scan, True, [])
    if not trigger:
        raise HTTPException(status_code=500, detail="Jenkins trigger failed")
    set_analysis_queued(session, project, trigger)
    log_ci_action(
        session,
        request,
        project,
        "ci_trigger_analysis",
        (
            f"branch={active_branch}, commit={commit_id}, first_scan={first_scan}, "
            f"build={trigger.display_label}"
        ),
    )
    session.commit()
    session.refresh(project)
    link_label = trigger.display_label
    return _ci_panel_response(
        request,
        project,
        session,
        active_branch=active_branch,
        ci_toast_key="ci_toast_analysis_started",
        ci_toast_url=trigger.console_url,
        ci_toast_link_text=link_label,
    )
