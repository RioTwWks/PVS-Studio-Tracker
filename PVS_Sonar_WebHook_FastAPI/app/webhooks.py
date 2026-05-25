from fastapi import Request, HTTPException, Depends, status, BackgroundTasks
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import os
import re
import stat
from pydantic import BaseModel
from typing import Optional, Dict
from sqlalchemy.orm import Session
from subprocess import check_output

from .database import get_db
from . import crud
from .config import settings
from .sonarqube_api_client import sonarqube_client
from .rate_limiter import limiter, RateLimits
from .logging_config import get_logger, ContextFilter
from .services import check_git_changes, check_tfvc_changes, check_tfvc_merge
from .services.jenkins_service import trigger_jenkins_build

import urllib3 # работа с HTTP-запросами
# Отключаем предупреждения '1097: InsecureRequestWarning'
urllib3.disable_warnings(category=urllib3.exceptions.InsecureRequestWarning)

# Get logger for webhook module
logger = get_logger("tfs_webhook", log_dir="logs/webhooks", add_file_handler=True)

# Add context filter
context_filter = ContextFilter()
for handler in logger.handlers:
    handler.addFilter(context_filter)

security = HTTPBasic()

class RepoContext(BaseModel):
    type: str
    name: str
    proj: str
    group: str

class TFVCEvent(BaseModel):
    eventType: str
    resource: Dict
    detailedMessage: Optional[Dict] = None
    message: Optional[Dict] = None

class GitEvent(BaseModel):
    eventType: str
    resource: Dict
    detailedMessage: Optional[Dict] = None
    message: Optional[Dict] = None

# Проверка Basic Authentication
def authenticate(credentials: HTTPBasicCredentials = Depends(security)):
    correct_username = credentials.username == settings.WEBHOOK_USERNAME
    correct_password = credentials.password == settings.WEBHOOK_PASSWORD

    if not (correct_username and correct_password):
        logger.error(
            f"Ошибка авторизации: {credentials.username}",
            extra={"repo_type": "AUTH", "repo_name": "SECURITY"}
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

# Извлечение информации о репозитории из заголовков
def get_repo_context(request: Request) -> RepoContext:
    logger.info(f"Извлечение информации о репозитории из заголовков")
    repo_type = request.headers.get("X-TFS-Repo-Type", "Unknown")
    repo_name = request.headers.get("X-TFS-Repo-Name", "Unnamed")
    proj_name = request.headers.get("X-TFS-Proj-Name", "Unproj")
    group_name = request.headers.get("X-TFS-Group-Name", "Ungroup")

    return RepoContext(type=repo_type, name=repo_name, proj=proj_name, group=group_name)

# Получение данных проекта из БД
def get_project_from_db(sonar_name: str, db: Session):
    logger.info(f"Получение данных проекта {sonar_name} из БД")
    project = crud.get_project_by_name(db, sonar_name)  # Используем существующую функцию [1]
    if not project:
        logger.error("Проект не найден в БД", extra={"repo_name": sonar_name})
        return None
    return project

# Сброс атрибута 'только для чтения' и повторная попытка
def remove_readonly(func, path, _):
    os.chmod(path, stat.S_IWRITE)
    func(path)


# Запуск Jenkins Job
def trigger_jenkins_job(project, commit_id: str, first_scan, linux_build, modified_files):
    """
    Запуск Jenkins job для анализа проекта.

    Функция Wrapper для обратной совместимости.
    Используйте trigger_jenkins_build из services для нового кода.
    """
    return trigger_jenkins_build(
        project=project,
        commit_id=commit_id,
        first_scan=first_scan,
        linux_build=linux_build,
        modified_files=modified_files if modified_files else []
    )

# Сохранение last.changeset
def update_last_changeset(project, commit_id: str, db: Session):
    logger.info(f"Обновление last.changeset {commit_id}")
    project.last_processed_changeset = commit_id
    db.commit()
    db.refresh(project)

# Обработка события TFVC
def process_tfvc_event(payload: TFVCEvent, repo_ctx: RepoContext, db: Session):
    logger.info(f"Обработка события TFVC")
    try:
        changeset = payload.resource
        changeset_id = changeset.get("changesetId", "N/A")
        logger.info(f"payload = {payload}")
        logger.info(f"changeset = {changeset}")

        try:
            repo_name = repo_ctx.name.replace("%20", " ")
            repo_proj = repo_ctx.proj.replace("%20", " ")
        except:
            repo_name = repo_ctx.name
            repo_proj = repo_ctx.proj

        logger.info(
            f"TFVC Changeset: {changeset_id}, Repo: {repo_name}, Project name: {repo_proj}, Group project: {repo_ctx.group}",
            extra={
                "repo_type": repo_ctx.type,
                "repo_name": repo_name,
                "proj_name": repo_proj,
                "group_proj": repo_ctx.group
            }
        )

        # Поиск проекта в БД
        # Обрабатываем случай когда repo_name не содержит '/'
        match = re.match(r'([^/]+/[^/]+)/(.*)', repo_name)
        if match:
            repo_name_parts = list(match.groups())
            logger.info(f"repo_name_parts = {repo_name_parts}")
        else:
            repo_name_parts = [match]
        if len(repo_name_parts) < 2:
            logger.error(f"Некорректный формат repo_name: '{repo_name}'. Ожидается формат 'Project/Branch'")
            return

        projects = crud.get_project_by_tfs_path_branch(db, f"{repo_name_parts[0]}", f"{repo_name_parts[1]}")
        logger.info(f"Найдены проекты в БД")
        for project in projects:
            logger.info(f"{project.tfs_path}/{project.another_branch} == {repo_name}")

            if project.cvs_system != "TFVC":
                logger.info(f"Проект {project.sonar_project_name} — Git. Пропускаем")
                continue

            elif f"{project.tfs_path}/{project.another_branch}" == f"{repo_name}":
                logger.info(f"Проект {repo_proj} существует в БД")

                # Проверяем изменения
                modified_files, first_scan, composition_changed, cmake_changed = check_tfvc_changes(project, project.last_processed_changeset, changeset_id, repo_name)
                if not modified_files:
                    logger.info("Нет изменений файлов C/C++/C# в TFVC")
                    return
                elif composition_changed or cmake_changed:
                    logger.info(f"Изменённые файлы: {modified_files}, добавленны/удалённы файлы: {composition_changed}, CMake файлы: {cmake_changed}")

                    # Запускаем Jenkins
                    trigger_jenkins_job(project, changeset_id, first_scan, True, modified_files)

                    # Обновляем last.changeset в БД
                    update_last_changeset(project, changeset_id, db)
                    return
                else:
                    logger.info(f"Изменённые файлы: {modified_files}")

                    # Запускаем Jenkins
                    trigger_jenkins_job(project, changeset_id, first_scan, False, modified_files)

                    # Обновляем last.changeset в БД
                    update_last_changeset(project, changeset_id, db)
                    return

            elif f"{project.tfs_path}" == f"{repo_name.split('/')[0]}":
                logger.info(f"{project.tfs_path} == {repo_name.split('/')[0]}")
                path_change = check_tfvc_merge(changeset_id)

                # Если path_change None (нет merge sources), пропускаем обработку
                if not path_change:
                    logger.info(f"Нет merge sources в changeset {changeset_id}. Пропускаем.")
                    return

                if project.another_branch.count("/") == 0:
                    logger.info(f"Проект {project.sonar_project_name} лежит в 'Main'")
                    branch = path_change.split("/", 2)[2]
                    logger.info(f"Создание проекта релизной версии на анализ {project.sonar_project_name} с веткой {branch}")
                    project_data = {
                        "group_id": project.group_id,
                        "author_email": project.author_email,
                        "sonar_project_name": f"{project.sonar_project_name}_{branch.split("/")[-1]}",
                        "sonar_project_key": f"{project.sonar_project_key}_{branch.split("/")[-1]}",
                        "jira_project": project.jira_project,
                        "cvs_system": project.cvs_system,
                        "tfs_path": project.tfs_path,
                        "sub_modules": project.sub_modules,
                        "another_branch": branch,
                        "life_time": project.life_time,
                        "cmake_msbuild": project.cmake_msbuild,
                        "select_vcxproj": project.select_vcxproj,
                        "pvs_exclude_vcxproj": project.pvs_exclude_vcxproj,
                        "pvs_exclude_path": project.pvs_exclude_path,
                        "pvs_check_conf_name": project.pvs_check_conf_name,
                        "pvs_check_arch": project.pvs_check_arch,
                        "cmake_win_commands": project.cmake_win_commands,
                        "cmake_linux_commands": project.cmake_linux_commands,
                        "disabled": False,
                        "last_processed_changeset": "",
                        "version": "",
                        "disable_jira": True,
                    }
                    crud.create_project(db, project_data)
                    sonarqube_client.create_sq_project(
                        f"{project.sonar_project_key}_{branch.split("/")[-1]}",
                        f"{project.sonar_project_name}_{branch.split("/")[-1]}",
                        branch
                    )
                    logger.info(f"Добавлен проект: {project.sonar_project_name}_{branch.split("/")[-1]} с веткой {branch}")

                    # Запускаем Jenkins
                    new_project = crud.get_project_by_name(db, f"{project.sonar_project_name}_{branch.split('/')[-1]}")
                    trigger_jenkins_job(new_project, changeset_id, "YES", True, modified_files)

                    # Обновляем last.changeset в БД
                    update_last_changeset(new_project, changeset_id, db)
                    return
                elif path_change and project.another_branch.split("/", 1)[1] == path_change.split("/", 3)[3]:
                    logger.info(f"{project.another_branch.split('/', 1)[1] == path_change.split('/', 3)[3]}")
                    branch = repo_name.split("/", 1)[1]
                    logger.info(f"Создание проекта релизной версии на анализ {project.sonar_project_name} с веткой {branch}")
                    project_data = {
                        "group_id": project.group_id,
                        "author_email": project.author_email,
                        "sonar_project_name": f"{project.sonar_project_name}_{branch.split("/")[-1]}",
                        "sonar_project_key": f"{project.sonar_project_key}_{branch.split("/")[-1]}",
                        "jira_project": project.jira_project,
                        "cvs_system": project.cvs_system,
                        "tfs_path": project.tfs_path,
                        "sub_modules": project.sub_modules,
                        "another_branch": branch,
                        "life_time": project.life_time,
                        "cmake_msbuild": project.cmake_msbuild,
                        "select_vcxproj": project.select_vcxproj,
                        "pvs_exclude_vcxproj": project.pvs_exclude_vcxproj,
                        "pvs_exclude_path": project.pvs_exclude_path,
                        "pvs_check_conf_name": project.pvs_check_conf_name,
                        "pvs_check_arch": project.pvs_check_arch,
                        "cmake_win_commands": project.cmake_win_commands,
                        "cmake_linux_commands": project.cmake_linux_commands,
                        "disabled": False,
                        "last_processed_changeset": "",
                        "version": "",
                        "disable_jira": True,
                    }
                    crud.create_project(db, project_data)
                    sonarqube_client.create_sq_project(
                        f"{project.sonar_project_key}_{branch.split("/")[-1]}",
                        f"{project.sonar_project_name}_{branch.split("/")[-1]}",
                        branch
                    )
                    logger.info(f"Добавлен проект: {project.sonar_project_name}_{branch.split("/")[-1]} с веткой {branch}")

                    # Запускаем Jenkins
                    new_project = crud.get_project_by_name(db, f"{project.sonar_project_name}_{branch.split("/")[-1]}")
                    trigger_jenkins_job(new_project, changeset_id, "YES", True, modified_files)

                    # Обновляем last.changeset в БД
                    update_last_changeset(new_project, changeset_id, db)
                    return
            else:
                logger.info(f"Пропускаем элемент БД {project.sonar_project_name}")

    except Exception as e:
        logger.error(
            f"TFVC processing error: {str(e)}", 
            extra={
                "repo_type": repo_ctx.type,
                "repo_name": repo_name,
                "proj_name": repo_proj,
                "group_proj": repo_ctx.group
            },
            exc_info=True
        )

# Возвращает commit‑id первого коммита, если он присутствует в payload, иначе берёт `newObjectId` из `refUpdates` (это последний коммит в push).
def _extract_commit_id(push_data: dict) -> str:
    # 1 Попытаться взять из списка commits (может быть, если включён detailed view)
    commits = push_data.get("commits")
    if isinstance(commits, list) and commits:
        # Azure DevOps иногда называется `commitId`, иногда `id`
        return commits[0].get("commitId") or commits[0].get("id", "Unknown")

    # 2 Если commits нет – используем newObjectId из refUpdates
    ref_updates = push_data.get("refUpdates", [])
    if ref_updates:
        return ref_updates[0].get("newObjectId", "Unknown")

    # 3 Фолбэк – неизвестно
    return "Unknown"

# Обработка события Git
def process_git_event(payload: GitEvent, repo_ctx: RepoContext, db: Session):
    logger.info(f"Обработка события Git")
    try:
        push_data = payload.resource
        push_id = _extract_commit_id(push_data)
        repo_name = push_data.get("repository", {}).get("name", "Unknown")
        repo_proj  = push_data.get("repository", {}).get("project", {}).get("name", "Unknown")

        branch = "Unknown"
        ref_updates = push_data.get("refUpdates", [])
        if ref_updates:
            branch = ref_updates[0].get("name", "Unknown").replace("refs/heads/", "")

        try:
            repo_name = repo_ctx.name.replace("%20", " ")
            repo_proj = repo_ctx.proj.replace("%20", " ")
        except:
            pass

        logger.info(
            f"Git Push: Repo={repo_name}, Branch={branch}, Commit={push_id}, Project name: {repo_proj}, Group project: {repo_ctx.group}",
            extra={
                "repo_type": getattr(repo_ctx, "type", "Unknown"),
                "repo_name": repo_name,
                "proj_name": repo_proj,
                "group_proj": getattr(repo_ctx, "group", "Unknown"),
            }
        )

        # Проверка обновления данного приложения
        if repo_name == "SAST" and repo_proj == "PVS_Sonar_WebHook_FastAPI":
            output = check_output(['git', 'pull'], cwd='../', encoding='UTF-8')
            if 'Updating' in output and 'Aborting' not in output:
                logger.info(f"Обновление приложения")
            else:
                logger.error(f"Ошибка обновления приложения")
            return

        if push_id == "0000000000000000000000000000000000000000":
            logger.info(f"Удаление ветки. Пропускаем")
            return

        # Поиск проекта в БД
        project = crud.get_project_by_name(db, f"{repo_proj}_{branch.split('/')[-1]}")
        if not project:
            project = crud.get_project_by_name(db, repo_proj)
            if not project:
                logger.error(f"Не найден проект {repo_proj} в БД")
                return

        logger.info(f"Найден проект в БД: {project.sonar_project_name}")

        # Проверка, отключен ли проект
        if project.disabled:
            logger.warning(f"Project {project.sonar_project_name} is disabled. Skipping.")
            return

        if project.another_branch == branch:
            # Проверяем изменения
            modified_files, first_scan, composition_changed, cmake_changed = check_git_changes(project, project.last_processed_changeset, push_id)
            if not modified_files:
                logger.info("Нет изменений файлов C/C++/C# в Git")
                return
            elif composition_changed or cmake_changed:
                logger.info(f"Изменённые файлы: {modified_files}, добавленны/удалённы файлы: {composition_changed}, CMake файлы: {cmake_changed}")

                # Запускаем Jenkins
                trigger_jenkins_job(project, push_id, first_scan, True, modified_files)

                # Обновляем last.changeset в БД
                update_last_changeset(project, push_id, db)
                return
            else:
                logger.info(f"Изменённые файлы: {modified_files}")

                # Запускаем Jenkins
                trigger_jenkins_job(project, push_id, first_scan, False, modified_files)

                # Обновляем last.changeset в БД
                update_last_changeset(project, push_id, db)
                return

        elif project.another_branch != branch and 'release' in branch:
            # Сначала проверяем изменения
            modified_files, first_scan, composition_changed, cmake_changed = check_git_changes(project, project.last_processed_changeset, push_id)

            # Если нет изменений, не создаем новый проект
            if not modified_files:
                logger.info("Нет изменений файлов C/C++/C# в Git. Пропускаем создание релизного проекта.")
                return

            if 'CCS' in branch:
                project = crud.get_project_by_name(db, f"ClientCodeSubstitute_{branch.split('/')[-1]}")
                logger.info(f"Релизная ветка ClientCodeSubstitute")
                project_data = {
                    "group_id": project.group_id,
                    "author_email": project.author_email,
                    "sonar_project_name": f"{project.sonar_project_name}_{branch.split("/")[-1]}",
                    "sonar_project_key": f"{project.sonar_project_key}_{branch.split("/")[-1]}",
                    "jira_project": project.jira_project,
                    "cvs_system": project.cvs_system,
                    "tfs_path": project.tfs_path,
                    "sub_modules": project.sub_modules,
                    "another_branch": branch,
                    "life_time": project.life_time,
                    "cmake_msbuild": project.cmake_msbuild,
                    "select_vcxproj": project.select_vcxproj,
                    "pvs_exclude_vcxproj": project.pvs_exclude_vcxproj,
                    "pvs_exclude_path": project.pvs_exclude_path,
                    "pvs_check_conf_name": project.pvs_check_conf_name,
                    "pvs_check_arch": project.pvs_check_arch,
                    "cmake_win_commands": project.cmake_win_commands,
                    "cmake_linux_commands": project.cmake_linux_commands,
                    "disabled": False,
                    "last_processed_changeset": "",
                    "version": "",
                    "disable_jira": True,
                }
                crud.create_project(db, project_data)
                sonarqube_client.create_sq_project(
                    f"{project.sonar_project_key}_{branch.split("/")[-1]}",
                    f"{project.sonar_project_name}_{branch.split("/")[-1]}",
                    branch
                )
                logger.info(f"Добавлен проект: {project.sonar_project_name}_{branch.split("/")[-1]} с веткой {branch}")

                # Запускаем Jenkins
                new_project = crud.get_project_by_name(db, f"{project.sonar_project_name}_{branch.split("/")[-1]}")
                trigger_jenkins_job(new_project, push_id, "YES", True, modified_files)

                # Обновляем last.changeset в БД
                update_last_changeset(new_project, push_id, db)
                return
            else:
                logger.info(f"Создание проекта на анализ {project.sonar_project_name} с веткой {branch}")
                project_data = {
                    "group_id": project.group_id,
                    "author_email": project.author_email,
                    "sonar_project_name": f"{project.sonar_project_name}_{branch.split("/")[-1]}",
                    "sonar_project_key": f"{project.sonar_project_key}_{branch.split("/")[-1]}",
                    "jira_project": project.jira_project,
                    "cvs_system": project.cvs_system,
                    "tfs_path": project.tfs_path,
                    "sub_modules": project.sub_modules,
                    "another_branch": branch,
                    "life_time": project.life_time,
                    "cmake_msbuild": project.cmake_msbuild,
                    "select_vcxproj": project.select_vcxproj,
                    "pvs_exclude_vcxproj": project.pvs_exclude_vcxproj,
                    "pvs_exclude_path": project.pvs_exclude_path,
                    "pvs_check_conf_name": project.pvs_check_conf_name,
                    "pvs_check_arch": project.pvs_check_arch,
                    "cmake_win_commands": project.cmake_win_commands,
                    "cmake_linux_commands": project.cmake_linux_commands,
                    "disabled": False,
                    "last_processed_changeset": "",
                    "version": "",
                    "disable_jira": True,
                }
                crud.create_project(db, project_data)
                sonarqube_client.create_sq_project(
                    f"{project.sonar_project_key}_{branch.split("/")[-1]}",
                    f"{project.sonar_project_name}_{branch.split("/")[-1]}",
                    branch
                )
                logger.info(f"Добавлен проект: {project.sonar_project_name}_{branch.split("/")[-1]} с веткой {branch}")

                # Запускаем Jenkins
                new_project = crud.get_project_by_name(db, f"{project.sonar_project_name}_{branch.split("/")[-1]}")
                trigger_jenkins_job(new_project, push_id, "YES", True, modified_files)

                # Обновляем last.changeset в БД
                update_last_changeset(new_project, push_id, db)
                return

    except Exception as e:
        logger.error(
            f"Git processing error: {str(e)}", 
            extra={
                "repo_type": repo_ctx.type,
                "repo_name": repo_name,
                "proj_name": repo_proj,
                "group_proj": repo_ctx.group
            },
            exc_info=True
        )

# Эндпоинт для вебхуков
@limiter.limit(RateLimits.WEBHOOK)
async def handle_webhook(
    background_tasks: BackgroundTasks,
    request: Request,
    username: str = Depends(authenticate),
    repo_ctx: RepoContext = Depends(get_repo_context),
    db: Session = Depends(get_db)):

    logger.info(
        f"Получен вебхук от {request.client.host}",
        extra={
            "repo_type": repo_ctx.type,
            "repo_name": repo_ctx.name
        }
    )

    try:
        payload_data = await request.json()
    except Exception as e:
        logger.error(
            f"Ошибка JSON: {str(e)}",
            extra={
                "repo_type": repo_ctx.type,
                "repo_name": repo_ctx.name
            }
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload"
        )

    # Добавляем фоновую задачу для обработки
    if repo_ctx.type == "TFVC":
        try:
            payload = TFVCEvent(**payload_data)
            # Передаем db в фоновую задачу
            background_tasks.add_task(process_tfvc_event, payload, repo_ctx, db)
        except Exception as e:
            logger.error(
                f"TFVC payload validation error: {str(e)}",
                extra={
                    "repo_type": repo_ctx.type,
                    "repo_name": repo_ctx.name
                }
            )
    elif repo_ctx.type == "Git":
        try:
            payload = GitEvent(**payload_data)
            # Передаем db в фоновую задачу
            background_tasks.add_task(process_git_event, payload, repo_ctx, db)
        except Exception as e:
            logger.error(
                f"Git payload validation error: {str(e)}",
                extra={
                    "repo_type": repo_ctx.type,
                    "repo_name": repo_ctx.name
                }
            )
    else:
        logger.warning(
            f"Unsupported repo type: {repo_ctx.type}",
            extra={"repo_type": repo_ctx.type, "repo_name": repo_ctx.name}
        )

    return {
        "status": "accepted",
        "repo_type": repo_ctx.type,
        "repo_name": repo_ctx.name,
        "event_type": payload_data.get("eventType", "unknown")
    }

# Эндпоинт для проверки работоспособности вебхуков
@limiter.limit(RateLimits.HEALTH_CHECK)
def health_check(request: Request):
    logger.info("Health check request", extra={"repo_type": "SYSTEM", "repo_name": "HEALTH"})
    return {"status": "ok", "service": "tfs-webhook"}
