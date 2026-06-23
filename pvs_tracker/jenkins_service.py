"""Jenkins CI trigger for SAST projects."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Optional
import urllib3
from urllib.parse import quote

from jenkinsapi.custom_exceptions import JenkinsAPIException, NotBuiltYet
from jenkinsapi.queue import QueueItem

from pvs_tracker.ci_config import ci_settings
from pvs_tracker.models import Project
from pvs_tracker.project_ci import project_analysis_branch, project_repo_path

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

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


@dataclass(frozen=True)
class JenkinsBuildSnapshot:
    """Сборка или элемент очереди Jenkins, относящиеся к проекту."""

    build_number: Optional[int]
    queue_id: Optional[int]
    status: str
    label: str
    console_url: str
    timestamp_ms: Optional[int] = None
    why: Optional[str] = None
    is_selected: bool = False


_PROJECT_SLUG_PARAM_KEYS = ("TRACKER_PROJECT_SLUG", "SONAR_PROJECT_KEY")


def jenkins_job_console_url(job_name: str, build_number: int) -> str:
    """Прямая ссылка на /console для известного номера сборки."""
    base = ci_settings.JENKINS_URL.rstrip("/")
    segments = [p for p in job_name.split("/") if p]
    job_path = "/".join(f"job/{quote(seg)}" for seg in segments)
    return f"{base}/{job_path}/{build_number}/console"


def _project_slug(project: Project) -> str:
    return (project.slug or project.name or "").strip()


def _params_match_project(params: dict[str, Any], slug: str) -> bool:
    if not slug:
        return False
    for key in _PROJECT_SLUG_PARAM_KEYS:
        value = params.get(key)
        if value is not None and str(value).strip() == slug:
            return True
    return False


def _build_status_label(build: Any) -> str:
    if build.is_running():
        return "RUNNING"
    status = build.get_status()
    return status or "UNKNOWN"


def _snapshot_sort_key(snapshot: JenkinsBuildSnapshot) -> tuple[int, int, int]:
    status_rank = {"QUEUED": 0, "RUNNING": 1}.get(snapshot.status, 2)
    build_number = snapshot.build_number or 0
    queue_id = snapshot.queue_id or 0
    return (status_rank, -build_number, -queue_id)


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

    def list_project_builds(
        self,
        project: Project,
        *,
        limit: int = 15,
    ) -> list[JenkinsBuildSnapshot]:
        """Сборки и элементы очереди Jenkins job для slug проекта."""
        slug = _project_slug(project)
        if not slug:
            return []

        job_name = ci_settings.JENKINS_JOB_NAME
        snapshots: list[JenkinsBuildSnapshot] = []
        seen_builds: set[int] = set()
        seen_queues: set[int] = set()

        queue = self.jenkins.get_queue()
        for queue_item in queue.get_queue_items_for_job(job_name):
            params = queue_item.get_parameters() or {}
            if not _params_match_project(params, slug):
                continue
            queue_id = int(queue_item.queue_id)
            if queue_id in seen_queues:
                continue
            seen_queues.add(queue_id)
            try:
                build_number = queue_item.get_build_number()
                build = queue_item.get_build()
                seen_builds.add(build_number)
                snapshots.append(
                    JenkinsBuildSnapshot(
                        build_number=build_number,
                        queue_id=queue_id,
                        status=_build_status_label(build),
                        label=f"#{build_number}",
                        console_url=f"{build.baseurl.rstrip('/')}/console",
                        timestamp_ms=build.get_timestamp(),
                    )
                )
            except NotBuiltYet:
                snapshots.append(
                    JenkinsBuildSnapshot(
                        build_number=None,
                        queue_id=queue_id,
                        status="QUEUED",
                        label=f"queue #{queue_id}",
                        console_url=_queue_item_web_url(queue_item),
                        why=queue_item.why,
                    )
                )

        job = self.jenkins[job_name]
        for build_number in sorted(job.get_build_ids(), reverse=True):
            if build_number in seen_builds:
                continue
            build = job.get_build(build_number)
            params = build.get_params()
            if not _params_match_project(params, slug):
                continue
            seen_builds.add(build_number)
            snapshots.append(
                JenkinsBuildSnapshot(
                    build_number=build_number,
                    queue_id=None,
                    status=_build_status_label(build),
                    label=f"#{build_number}",
                    console_url=f"{build.baseurl.rstrip('/')}/console",
                    timestamp_ms=build.get_timestamp(),
                )
            )
            if len(seen_builds) >= limit:
                break

        snapshots.sort(key=_snapshot_sort_key)
        return snapshots[:limit]

    def get_project_build_console(
        self,
        project: Project,
        *,
        build_number: Optional[int] = None,
        queue_id: Optional[int] = None,
    ) -> tuple[str, str]:
        """Текст консоли и статус выбранной сборки или элемента очереди."""
        job_name = ci_settings.JENKINS_JOB_NAME
        if queue_id is not None and build_number is None:
            queue_item = self.jenkins.get_queue()[str(queue_id)]
            try:
                build = queue_item.get_build()
                return build.get_console(), _build_status_label(build)
            except NotBuiltYet:
                lines = [f"Build is waiting in Jenkins queue (#{queue_id})."]
                if queue_item.why:
                    lines.append(queue_item.why)
                return "\n".join(lines), "QUEUED"

        if build_number is None:
            return "", "UNKNOWN"

        build = self.jenkins[job_name].get_build(build_number)
        params = build.get_params()
        slug = _project_slug(project)
        if slug and not _params_match_project(params, slug):
            raise ValueError(f"Build #{build_number} does not belong to project {slug}")
        return build.get_console(), _build_status_label(build)


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


def fetch_project_ci_builds(
    project: Project,
    *,
    limit: int = 15,
) -> tuple[list[JenkinsBuildSnapshot], Optional[str]]:
    """Список сборок проекта; при ошибке Jenkins — пустой список и текст ошибки."""
    if not ci_settings.JENKINS_URL.strip():
        return [], "Jenkins URL is not configured"
    try:
        return get_jenkins_service().list_project_builds(project, limit=limit), None
    except JenkinsAPIException as exc:
        logger.warning("Jenkins API error while listing builds: %s", exc)
        return [], f"Jenkins API error: {exc}"
    except Exception as exc:
        logger.warning("Failed to list Jenkins builds: %s", exc, exc_info=True)
        return [], f"Failed to connect to Jenkins: {exc}"


def get_project_build_console(
    project: Project,
    *,
    build_number: Optional[int] = None,
    queue_id: Optional[int] = None,
) -> tuple[str, str]:
    """Текст консоли; при ошибке — сообщение в теле и статус ERROR."""
    try:
        return get_jenkins_service().get_project_build_console(
            project,
            build_number=build_number,
            queue_id=queue_id,
        )
    except Exception as exc:
        logger.warning("Failed to fetch Jenkins console: %s", exc, exc_info=True)
        return f"Failed to load console output: {exc}", "ERROR"


def pick_default_build_selection(
    builds: list[JenkinsBuildSnapshot],
) -> tuple[Optional[int], Optional[int]]:
    """Выбрать сборку по умолчанию: активная (очередь/бег) или последняя."""
    if not builds:
        return None, None
    for snapshot in builds:
        if snapshot.status in ("QUEUED", "RUNNING"):
            if snapshot.build_number is not None:
                return snapshot.build_number, snapshot.queue_id
            return None, snapshot.queue_id
    first = builds[0]
    return first.build_number, first.queue_id if first.status == "QUEUED" else None


def mark_selected_build(
    builds: list[JenkinsBuildSnapshot],
    *,
    build_number: Optional[int],
    queue_id: Optional[int],
) -> list[JenkinsBuildSnapshot]:
    """Пометить выбранную строку в списке сборок."""
    selected_build = build_number
    selected_queue = queue_id
    if selected_build is None and selected_queue is None:
        selected_build, selected_queue = pick_default_build_selection(builds)

    marked: list[JenkinsBuildSnapshot] = []
    for snapshot in builds:
        is_selected = False
        if selected_build is not None and snapshot.build_number == selected_build:
            is_selected = True
        elif (
            selected_build is None
            and selected_queue is not None
            and snapshot.queue_id == selected_queue
            and snapshot.status == "QUEUED"
        ):
            is_selected = True
        marked.append(
            JenkinsBuildSnapshot(
                build_number=snapshot.build_number,
                queue_id=snapshot.queue_id,
                status=snapshot.status,
                label=snapshot.label,
                console_url=snapshot.console_url,
                timestamp_ms=snapshot.timestamp_ms,
                why=snapshot.why,
                is_selected=is_selected,
            )
        )
    return marked


def project_builds_have_active(builds: list[JenkinsBuildSnapshot]) -> bool:
    return any(snapshot.status in ("QUEUED", "RUNNING") for snapshot in builds)
