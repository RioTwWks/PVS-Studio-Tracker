"""Jenkins CI trigger for SAST projects."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import quote

from jenkinsapi.custom_exceptions import NotBuiltYet
from jenkinsapi.queue import QueueItem

from pvs_tracker.ci_config import ci_settings
from pvs_tracker.models import Project
from pvs_tracker.project_ci import project_analysis_branch, project_repo_path

logger = logging.getLogger(__name__)

# Сколько ждать появления номера сборки перед ссылкой на очередь (сек).
_BUILD_WAIT_SECONDS = 12.0
_BUILD_POLL_INTERVAL = 1.0


@dataclass(frozen=True)
class JenkinsTriggerResult:
    """Результат постановки job в очередь Jenkins."""

    build_number: Optional[int]
    queue_id: Optional[int]
    console_url: str
    display_label: str


def jenkins_job_console_url(job_name: str, build_number: int) -> str:
    """Прямая ссылка на /console для известного номера сборки."""
    base = ci_settings.JENKINS_URL.rstrip("/")
    segments = [p for p in job_name.split("/") if p]
    job_path = "/".join(f"job/{quote(seg)}" for seg in segments)
    return f"{base}/{job_path}/{build_number}/console"


def _queue_item_web_url(queue_item: QueueItem) -> str:
    url = (queue_item.baseurl or "").rstrip("/")
    if "/api/" in url:
        url = url.replace("/api/", "/")
    return f"{url}/"


def _build_console_url(queue_item: QueueItem) -> JenkinsTriggerResult:
    """Дождаться старта сборки и вернуть URL консоли (или страницы очереди)."""
    queue_id = int(queue_item.queue_id)
    deadline = time.monotonic() + _BUILD_WAIT_SECONDS

    while time.monotonic() < deadline:
        try:
            queue_item.poll()
            build_number = queue_item.get_build_number()
            build = queue_item.get_build()
            console_url = f"{build.baseurl.rstrip('/')}/console"
            return JenkinsTriggerResult(
                build_number=build_number,
                queue_id=queue_id,
                console_url=console_url,
                display_label=f"#{build_number}",
            )
        except NotBuiltYet:
            time.sleep(_BUILD_POLL_INTERVAL)

    queue_url = _queue_item_web_url(queue_item)
    logger.info(
        "Build not started within %.0fs, linking to queue item %s",
        _BUILD_WAIT_SECONDS,
        queue_id,
    )
    return JenkinsTriggerResult(
        build_number=None,
        queue_id=queue_id,
        console_url=queue_url,
        display_label=f"queue #{queue_id}",
    )

_jenkins_service: Optional["JenkinsService"] = None


class JenkinsService:
    def __init__(self) -> None:
        self._jenkins: Any = None

    @property
    def jenkins(self) -> Any:
        if self._jenkins is None:
            from jenkinsapi.jenkins import Jenkins

            self._jenkins = Jenkins(
                ci_settings.JENKINS_URL,
                username=ci_settings.JENKINS_USERNAME,
                password=ci_settings.JENKINS_TOKEN,
                ssl_verify=False,
                use_crumb=True,
                timeout=20,
            )
            logger.info("Connected to Jenkins %s", self._jenkins.version)
        return self._jenkins

    def trigger_build(
        self,
        project: Project,
        commit_id: str,
        first_scan: bool | str = False,
        linux_build: bool = False,
        modified_files: Optional[list[str]] = None,
    ) -> Optional[JenkinsTriggerResult]:
        if isinstance(first_scan, str):
            first_scan_bool = first_scan.upper() == "YES"
        else:
            first_scan_bool = bool(first_scan)

        if project.disabled:
            logger.warning("Project %s is disabled", project.name)
            return None

        try:
            build_params = self._prepare_build_params(
                project, commit_id, first_scan_bool, linux_build
            )
            files = self._prepare_file_uploads(project, modified_files or [])
            job = self.jenkins[ci_settings.JENKINS_JOB_NAME]
            queue_item = job.invoke(
                build_params=build_params,
                files={k: v for k, v in files.items() if v},
            )
            result = _build_console_url(queue_item)
            logger.info(
                "Jenkins build for %s: %s -> %s",
                project.name,
                result.display_label,
                result.console_url,
            )
            return result
        except Exception as e:
            logger.error("Jenkins trigger failed: %s", e, exc_info=True)
            return None

    def _prepare_build_params(
        self,
        project: Project,
        commit_id: str,
        first_scan: bool,
        linux_build: bool,
    ) -> dict[str, str]:
        slug = project.slug or project.name
        group = project.group_name or ""
        return {
            "GROUP": group,
            "AUTHOR_EMAIL": project.author_email or "",
            "TRACKER_PROJECT_NAME": project.name,
            "TRACKER_PROJECT_SLUG": slug,
            "SONAR_PROJECT_NAME": project.name,
            "SONAR_PROJECT_KEY": slug,
            "CVS_SYSTEM": project.cvs_system or "",
            "TFS_PATH": project_repo_path(project),
            "SUB_MODULES": str(project.sub_modules),
            "ANOTHER_BRANCH": project_analysis_branch(project),
            "LIFE_TIME": project.life_time or "",
            "CMAKE_MSBUILD": project.cmake_msbuild or "",
            "SELECT_VCXPROJ": project.select_vcxproj or "",
            "PVS_EXCLUDE_VCXPROJ": project.pvs_exclude_vcxproj or "",
            "PVS_EXCLUDE_PATH": project.pvs_exclude_path or "",
            "PVS_CHECK_CONF_NAME": project.pvs_check_conf_name or "",
            "PVS_CHECK_ARCH": project.pvs_check_arch or "",
            "COMMIT": commit_id or "",
            "FirstScan": "YES" if first_scan else "NO",
            "LinuxBuildAgain": "YES" if linux_build else "NO",
        }

    def _prepare_file_uploads(
        self,
        project: Project,
        modified_files: list[str],
    ) -> dict[str, str]:
        files_path = ""
        repo_path = project_repo_path(project)
        branch = project_analysis_branch(project)
        if modified_files:
            for file in modified_files:
                if project.cvs_system == "Git":
                    files_path += f"\n./{file}"
                elif project.cvs_system == "TFVC":
                    regular = repo_path.split("/")[1] + "/" + branch if "/" in repo_path else branch
                    try:
                        files_path += f"\n./{file.split(regular + '/')[1]}"
                    except (IndexError, ValueError):
                        files_path += f"\n./{file}"
        return {
            "cmake_conf.cmd": project.cmake_win_commands or "",
            "cmake_conf.sh": project.cmake_linux_commands or "",
            "modified_files.txt": files_path,
        }


def get_jenkins_service() -> JenkinsService:
    global _jenkins_service
    if _jenkins_service is None:
        _jenkins_service = JenkinsService()
    return _jenkins_service


def trigger_jenkins_build(
    project: Project,
    commit_id: str,
    first_scan: bool | str = False,
    linux_build: bool = False,
    modified_files: Optional[list[str]] = None,
) -> Optional[JenkinsTriggerResult]:
    return get_jenkins_service().trigger_build(
        project, commit_id, first_scan, linux_build, modified_files
    )
