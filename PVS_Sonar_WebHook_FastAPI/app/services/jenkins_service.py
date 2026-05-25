"""
Сервис Jenkins для операций CI/CD.

Обрабатывает:
- Запуск задач Jenkins
- Подготовка параметров сборки
- Загрузка файлов для сборок
"""

from typing import List, Optional, Dict
from jenkinsapi.jenkins import Jenkins

from app.logging_config import get_logger
from app.config import settings

logger = get_logger(__name__)


# Сервис для операций Jenkins CI/CD
class JenkinsService:

    # Инициализация подключения Jenkins
    def __init__(self):
        self.jenkins_url = settings.JENKINS_URL
        self.job_name = settings.JENKINS_JOB_NAME
        self.username = settings.JENKINS_USERNAME
        self.token = settings.JENKINS_TOKEN
        self._jenkins = None

    @property
    # Получить или создать подключение Jenkins
    def jenkins(self) -> Jenkins:
        if self._jenkins is None:
            self._jenkins = Jenkins(
                self.jenkins_url,
                username=self.username,
                password=self.token,
                ssl_verify=False,
                use_crumb=True,
                timeout=20
            )
            logger.info(f"Подключено к Jenkins: {self._jenkins.version}")
        return self._jenkins

    # Запустить сборку Jenkins для проекта
    def trigger_build(
        self,
        project,                                        # Объект проекта с конфигурацией сборки
        commit_id: str,                                 # ID коммита/changeset
        first_scan: bool = False,                       # True или "YES" если это первое сканирование
        linux_build: bool = False,                      # True если требуется сборка Linux
        modified_files: Optional[List[str]] = None      # Список изменённых путей файлов
    ) -> Optional[int]:
        # Преобразуем first_scan из строки в boolean если нужно
        if isinstance(first_scan, str):
            first_scan_bool = first_scan.upper() == "YES"
        else:
            first_scan_bool = bool(first_scan)

        logger.info(
            f"🔧 JENKINS BUILD: project={project.sonar_project_name}, "
            f"commit={commit_id or 'N/A'}, FirstScan={first_scan} ({first_scan_bool}), "
            f"last_processed_changeset={project.last_processed_changeset or 'N/A'}, "
            f"modified_files_count={len(modified_files) if modified_files else 0}"
        )

        if project.disabled:
            logger.warning(f"Проект {project.sonar_project_name} отключён")
            return None

        try:
            # Подготовка параметров сборки
            build_params = self._prepare_build_params(
                project, commit_id, first_scan_bool, linux_build
            )

            # Подготовка загрузок файлов
            files = self._prepare_file_uploads(project, modified_files)

            # Получение задачи и запуск сборки
            job = self.jenkins[self.job_name]
            build = job.invoke(
                build_params=build_params,
                files={k: v for k, v in files.items() if v}
            )

            logger.info(f"Сборка Jenkins запущена. Номер сборки: {build}")
            return build

        except Exception as e:
            logger.error(f"Ошибка запуска сборки Jenkins: {e}", exc_info=True)
            return None

    # Подготовка параметров сборки Jenkins
    def _prepare_build_params(
        self,
        project,
        commit_id: str,
        first_scan: bool,
        linux_build: bool
    ) -> Dict[str, str]:
        return {
            "GROUP": project.group,
            "AUTHOR_EMAIL": project.author_email,
            "SONAR_PROJECT_NAME": project.sonar_project_name,
            "SONAR_PROJECT_KEY": project.sonar_project_key,
            "CVS_SYSTEM": project.cvs_system,
            "TFS_PATH": project.tfs_path,
            "SUB_MODULES": str(project.sub_modules),
            "ANOTHER_BRANCH": project.another_branch,
            "LIFE_TIME": project.life_time,
            "CMAKE_MSBUILD": project.cmake_msbuild,
            "SELECT_VCXPROJ": project.select_vcxproj,
            "PVS_EXCLUDE_VCXPROJ": project.pvs_exclude_vcxproj,
            "PVS_EXCLUDE_PATH": project.pvs_exclude_path,
            "PVS_CHECK_CONF_NAME": project.pvs_check_conf_name,
            "PVS_CHECK_ARCH": project.pvs_check_arch,
            "COMMIT": commit_id or "",
            "FirstScan": "YES" if first_scan else "NO",
            "LinuxBuildAgain": "YES" if linux_build else "NO",
        }

    # Подготовка загрузок файлов для сборки Jenkins
    def _prepare_file_uploads(
        self,
        project,
        modified_files: Optional[List[str]]
    ) -> Dict[str, str]:
        files_path = ''

        if modified_files:
            for file in modified_files:
                if project.cvs_system == 'Git':
                    files_path += f'\n./{file}'
                elif project.cvs_system == 'TFVC':
                    regular = project.tfs_path.split('/')[1] + '/' + project.another_branch
                    try:
                        files_path += f'\n./{file.split(regular + "/")[1]}'
                    except (IndexError, ValueError):
                        files_path += f'\n./{file}'

        return {
            'cmake_conf.cmd': project.cmake_win_commands or '',
            'cmake_conf.sh': project.cmake_linux_commands or '',
            'modified_files.txt': files_path,
        }

    # Получить статус сборки Jenkins
    def get_build_status(self, build_number: int) -> Optional[str]:
        try:
            job = self.jenkins[self.job_name]
            build = job.get_build(build_number)
            return build.get_status()
        except Exception as e:
            logger.error(f"Ошибка получения статуса сборки: {e}", exc_info=True)
            return None


# Глобальный экземпляр сервиса Jenkins
_jenkins_service: Optional[JenkinsService] = None


# Получить или создать экземпляр сервиса Jenkins
def get_jenkins_service() -> JenkinsService:
    global _jenkins_service
    if _jenkins_service is None:
        _jenkins_service = JenkinsService()
    return _jenkins_service


# Вспомогательная функция для запуска сборки Jenkins
def trigger_jenkins_build(
    project,                                        # Объект проекта
    commit_id: str,                                 # ID коммита/changeset
    first_scan: bool = False,                       # True если первое сканирование
    linux_build: bool = False,                      # True если требуется сборка Linux
    modified_files: Optional[List[str]] = None      # Список изменённых файлов
) -> Optional[int]:
    service = get_jenkins_service()
    return service.trigger_build(project, commit_id, first_scan, linux_build, modified_files)
