"""CRUD and queries for CI-enabled projects."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session, select

from pvs_tracker.models import Project
from pvs_tracker.project_groups import group_name_from_id

logger = logging.getLogger(__name__)

EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def project_repo_path(project: Project) -> str:
    return (project.repo_path or project.git_url or "").strip()


def project_analysis_branch(project: Project) -> str:
    """Текущая ветка CI (синхронизирована с git_branch на дашборде)."""
    branch = (project.git_branch or project.analysis_branch or "").strip()
    return branch or "main"


def parse_sonar_form_fields(
    *,
    group_id: str | int,
    author_email: str,
    sonar_project_name: str,
    sonar_project_key: str,
    jira_project: str = "",
    cvs_system: str = "Git",
    tfs_path: str = "",
    another_branch: str = "",
    include_branch: bool = True,
    sub_modules: bool = False,
    life_time: str = "",
    cmake_msbuild: str = "CMake",
    select_vcxproj: str = "",
    pvs_exclude_vcxproj: str = "",
    pvs_exclude_path: str = "",
    pvs_check_conf_name: str = "",
    pvs_check_arch: str = "",
    cmake_win_commands: str = "",
    cmake_linux_commands: str = "",
    disabled: bool = False,
    disable_jira: bool = True,
) -> dict[str, Any]:
    """Нормализация полей формы (имена как в PVS_Sonar_WebHook_FastAPI)."""
    name = sonar_project_name.strip()
    if re.search(r"\s", name):
        raise ValueError("SonarQube Project Name не должен содержать пробелов")
    slug = (sonar_project_key or slug_from_name(name)).strip()
    data: dict[str, Any] = {
        "name": name,
        "slug": slug,
        "author_email": author_email.strip(),
        "group_name": group_name_from_id(group_id),
        "jira_project": jira_project.strip(),
        "cvs_system": cvs_system.strip(),
        "repo_path": tfs_path.strip(),
        "sub_modules": sub_modules,
        "life_time": life_time.strip() or None,
        "cmake_msbuild": cmake_msbuild.strip() or None,
        "select_vcxproj": select_vcxproj.strip(),
        "pvs_exclude_vcxproj": pvs_exclude_vcxproj.strip(),
        "pvs_exclude_path": pvs_exclude_path.strip(),
        "pvs_check_conf_name": pvs_check_conf_name.strip(),
        "pvs_check_arch": pvs_check_arch.strip(),
        "cmake_win_commands": cmake_win_commands,
        "cmake_linux_commands": cmake_linux_commands,
        "disabled": disabled,
        "disable_jira": disable_jira,
    }
    if include_branch:
        branch_val = another_branch.strip() or "main"
        data["analysis_branch"] = branch_val
        data["git_branch"] = branch_val
    return data


def validate_ci_project_data(data: dict[str, Any]) -> tuple[bool, str]:
    required = ["name", "author_email", "cvs_system", "repo_path", "pvs_check_conf_name", "pvs_check_arch"]
    missing = [f for f in required if not str(data.get(f) or "").strip()]
    if missing:
        return False, f"Missing required fields: {', '.join(missing)}"
    email = str(data.get("author_email", ""))
    if email and not EMAIL_RE.match(email):
        return False, "Invalid author_email"
    cvs = str(data.get("cvs_system", ""))
    if cvs not in ("Git", "TFVC"):
        return False, "cvs_system must be Git or TFVC"
    if re.search(r"\s", str(data.get("name", ""))):
        return False, "SonarQube Project Name must not contain spaces"
    return True, ""


def slug_from_name(name: str) -> str:
    base = re.sub(r"[^a-zA-Z0-9_-]+", "_", name.strip())
    return base[:80] or "project"


def get_project_by_id(session: Session, project_id: int) -> Optional[Project]:
    return session.get(Project, project_id)


def get_project_by_name(session: Session, name: str) -> Optional[Project]:
    return session.exec(select(Project).where(Project.name == name)).first()


def get_project_by_slug(session: Session, slug: str) -> Optional[Project]:
    return session.exec(select(Project).where(Project.slug == slug)).first()


def get_projects_by_repo_branch(
    session: Session, repo_path: str, analysis_branch: str
) -> list[Project]:
    stmt = select(Project).where(
        Project.repo_path == repo_path,
        Project.analysis_branch == analysis_branch,
    )
    return list(session.exec(stmt).all())


def list_ci_projects_grouped(session: Session) -> dict[str, list[Project]]:
    projects = list(session.exec(select(Project).order_by(Project.name)).all())
    grouped: dict[str, list[Project]] = {}
    for p in projects:
        key = p.group_name or "Ungrouped"
        grouped.setdefault(key, []).append(p)
    return grouped


def apply_ci_fields(project: Project, data: dict[str, Any]) -> None:
    for key, value in data.items():
        if hasattr(project, key):
            setattr(project, key, value)


def create_ci_project(session: Session, data: dict[str, Any]) -> Project:
    ok, msg = validate_ci_project_data(data)
    if not ok:
        raise ValueError(msg)
    name = str(data["name"]).strip()
    slug = str(data.get("slug") or slug_from_name(name)).strip()
    if get_project_by_name(session, name):
        raise ValueError(f"Project {name} already exists")
    if get_project_by_slug(session, slug):
        raise ValueError(f"Slug {slug} already exists")
    project = Project(
        name=name,
        slug=slug,
        language=str(data.get("language") or "c++"),
        author_email=str(data["author_email"]).strip(),
        group_name=str(data.get("group_name") or "Ungrouped").strip(),
        cvs_system=str(data["cvs_system"]).strip(),
        repo_path=str(data["repo_path"]).strip(),
        analysis_branch=str(data.get("analysis_branch") or data.get("git_branch") or "").strip(),
        jira_project=str(data.get("jira_project") or "").strip(),
        sub_modules=bool(data.get("sub_modules")),
        life_time=data.get("life_time"),
        cmake_msbuild=data.get("cmake_msbuild"),
        select_vcxproj=str(data.get("select_vcxproj") or ""),
        pvs_exclude_vcxproj=str(data.get("pvs_exclude_vcxproj") or ""),
        pvs_exclude_path=str(data.get("pvs_exclude_path") or ""),
        pvs_check_conf_name=str(data["pvs_check_conf_name"]).strip(),
        pvs_check_arch=str(data["pvs_check_arch"]).strip(),
        cmake_win_commands=str(data.get("cmake_win_commands") or ""),
        cmake_linux_commands=str(data.get("cmake_linux_commands") or ""),
        disabled=bool(data.get("disabled")),
        disable_jira=bool(data.get("disable_jira", True)),
        last_processed_changeset=str(data.get("last_processed_changeset") or ""),
        release_version=str(data.get("release_version") or ""),
    )
    if data.get("git_url"):
        project.git_url = str(data["git_url"])
    branch = str(data.get("git_branch") or data.get("analysis_branch") or "").strip() or "main"
    project.git_branch = branch
    project.analysis_branch = branch
    session.add(project)
    session.commit()
    session.refresh(project)
    logger.info("Created CI project %s (slug=%s)", project.name, project.slug)
    return project


def clone_ci_project(session: Session, source: Project) -> Project:
    suffix = "_clone"
    new_name = f"{source.name}{suffix}"
    base_slug = source.slug or slug_from_name(source.name)
    new_slug = f"{base_slug}{suffix}"
    n = 1
    while get_project_by_name(session, new_name):
        n += 1
        new_name = f"{source.name}{suffix}{n}"
        new_slug = f"{base_slug}{suffix}{n}"
    data = {
        "name": new_name,
        "slug": new_slug,
        "language": source.language,
        "author_email": source.author_email,
        "group_name": source.group_name,
        "cvs_system": source.cvs_system,
        "repo_path": source.repo_path,
        "analysis_branch": source.analysis_branch,
        "jira_project": source.jira_project,
        "sub_modules": source.sub_modules,
        "life_time": source.life_time,
        "cmake_msbuild": source.cmake_msbuild,
        "select_vcxproj": source.select_vcxproj,
        "pvs_exclude_vcxproj": source.pvs_exclude_vcxproj,
        "pvs_exclude_path": source.pvs_exclude_path,
        "pvs_check_conf_name": source.pvs_check_conf_name,
        "pvs_check_arch": source.pvs_check_arch,
        "cmake_win_commands": source.cmake_win_commands,
        "cmake_linux_commands": source.cmake_linux_commands,
        "disabled": source.disabled,
        "disable_jira": source.disable_jira,
    }
    return create_ci_project(session, data)


def update_last_changeset(session: Session, project: Project, changeset: str) -> None:
    project.last_processed_changeset = changeset
    session.add(project)
    session.commit()
    session.refresh(project)


def set_analysis_queued(
    session: Session,
    project: Project,
    trigger: Optional[object],
) -> None:
    from pvs_tracker.jenkins_service import JenkinsTriggerResult

    if isinstance(trigger, JenkinsTriggerResult):
        project.last_jenkins_build_id = trigger.build_number
        project.last_jenkins_build_url = trigger.console_url
    project.last_analysis_at = datetime.utcnow()
    session.add(project)
    session.commit()
    session.refresh(project)


def duplicate_release_project(
    session: Session, template: Project, branch: str, name_suffix: str
) -> Project:
    new_name = f"{template.name}_{name_suffix}"
    new_slug = f"{(template.slug or slug_from_name(template.name))}_{name_suffix}"
    if get_project_by_name(session, new_name):
        existing = get_project_by_name(session, new_name)
        if existing:
            return existing
    data = {
        "name": new_name,
        "slug": new_slug,
        "language": template.language,
        "author_email": template.author_email,
        "group_name": template.group_name,
        "cvs_system": template.cvs_system,
        "repo_path": template.repo_path,
        "analysis_branch": branch,
        "jira_project": template.jira_project,
        "sub_modules": template.sub_modules,
        "life_time": template.life_time,
        "cmake_msbuild": template.cmake_msbuild,
        "select_vcxproj": template.select_vcxproj,
        "pvs_exclude_vcxproj": template.pvs_exclude_vcxproj,
        "pvs_exclude_path": template.pvs_exclude_path,
        "pvs_check_conf_name": template.pvs_check_conf_name,
        "pvs_check_arch": template.pvs_check_arch,
        "cmake_win_commands": template.cmake_win_commands,
        "cmake_linux_commands": template.cmake_linux_commands,
        "disable_jira": True,
        "last_processed_changeset": "",
    }
    return create_ci_project(session, data)
