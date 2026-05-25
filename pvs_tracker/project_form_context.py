"""Контекст Jinja для формы проекта (поля как в Sonar-сервисе)."""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

from pvs_tracker.models import Project
from pvs_tracker.project_groups import group_id_from_name, group_name_from_id


def _jira_project_options() -> list[dict[str, str]]:
    try:
        from pvs_tracker.jira_service import get_jira_service

        svc = get_jira_service()
        if svc.is_connected():
            return [{"name": p.name, "key": p.key} for p in svc.client.projects()]
    except Exception:
        pass
    return []


def project_form_context(
    project: Optional[Project] = None,
    *,
    clone: bool = False,
    edit: bool = False,
    edit_id: Optional[int] = None,
    load_jira: bool = True,
) -> dict[str, Any]:
    current_date = date.today().strftime("%Y-%m")
    ctx: dict[str, Any] = {
        "current_date": current_date,
        "clone_proj": "true" if clone else "false",
        "edit_proj": "true" if edit else "false",
        "edit_id": edit_id or "",
        "all_jira_projects": _jira_project_options() if load_jira else [],
        "group_id": 1,
        "author_email": "",
        "sonar_project_name": "",
        "sonar_project_key": "",
        "jira_project": "",
        "cvs_system": "Git",
        "tfs_path": "",
        "sub_modules": False,
        "another_branch": "",
        "life_time": "",
        "cmake_msbuild": "CMake",
        "select_vcxproj": "",
        "pvs_exclude_vcxproj": "",
        "pvs_exclude_path": "",
        "pvs_check_conf_name": "",
        "pvs_check_arch": "",
        "cmake_win_commands": "",
        "cmake_linux_commands": "",
        "disabled": False,
        "disable_jira": True,
    }
    if not project:
        return ctx

    ctx.update(
        {
            "group_id": group_id_from_name(project.group_name),
            "author_email": project.author_email or "",
            "sonar_project_name": project.name,
            "sonar_project_key": "" if clone else (project.slug or ""),
            "jira_project": project.jira_project or "",
            "cvs_system": project.cvs_system or "Git",
            "tfs_path": project.repo_path or project.git_url or "",
            "sub_modules": project.sub_modules,
            "another_branch": project.analysis_branch or project.git_branch or "",
            "life_time": project.life_time or "",
            "cmake_msbuild": project.cmake_msbuild or "CMake",
            "select_vcxproj": project.select_vcxproj or "",
            "pvs_exclude_vcxproj": project.pvs_exclude_vcxproj or "",
            "pvs_exclude_path": project.pvs_exclude_path or "",
            "pvs_check_conf_name": project.pvs_check_conf_name or "",
            "pvs_check_arch": project.pvs_check_arch or "",
            "cmake_win_commands": project.cmake_win_commands or "",
            "cmake_linux_commands": project.cmake_linux_commands or "",
            "disabled": project.disabled,
            "disable_jira": project.disable_jira,
        }
    )
    return ctx
