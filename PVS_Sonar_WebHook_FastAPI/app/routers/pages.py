"""
Роутеры главных страниц.

Отображение форм создания/редактирования проектов и списка проектов.
"""

from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import HTMLResponse
from fastapi import Response
from sqlalchemy.orm import Session
from typing import Optional, Dict, List
from datetime import date
import uuid

from app import crud
from app.database import get_db
from app.logging_config import get_logger
from app.rate_limiter import limiter, RateLimits
from app.jira_issue import get_jira_client
from app.admin_utils import get_client_info, is_admin
from app.templates import get_templates

logger = get_logger(__name__)

router = APIRouter(tags=["pages"])

# Инициализация шаблонов
templates = get_templates()

# Временное хранилище для flash-сообщений (в production используйте Redis)
flash_messages: Dict[str, List[str]] = {}


# Добавляет flash-сообщение в cookies
def add_flash_message(response: Response, message: str, category: str = "success"):
    flash_id = str(uuid.uuid4())
    if flash_id not in flash_messages:
        flash_messages[flash_id] = []
    flash_messages[flash_id].append(f"{category}:{message}")
    response.set_cookie("flash_id", flash_id, max_age=300)  # Сообщение живёт 5 секунд


# Извлекает flash-сообщения из cookies и очищает cookie
def get_flash_messages(request: Request) -> List[tuple]:
    flash_id = request.cookies.get("flash_id")
    if not flash_id or flash_id not in flash_messages:
        return []

    messages = []
    for message in flash_messages.pop(flash_id, []):
        if ":" in message:
            category, text = message.split(":", 1)
            messages.append((category, text))

    return messages


# Очищает cookie flash-сообщений
def clear_flash_cookie(response: Response) -> Response:
    response.delete_cookie("flash_id")
    return response


@router.get("/", response_class=HTMLResponse)
@limiter.limit(RateLimits.PUBLIC_FORM)
async def read_root(
    request: Request,
    clone_id: Optional[int] = Query(None),
    edit_id: Optional[int] = Query(None),
    db: Session = Depends(get_db)
):
    # Отобразить форму создания/редактирования проекта

    # Инициализация значений по умолчанию
    current_date = date.today().strftime('%Y-%m')
    group_id = ''
    author_email = ''
    sonar_project_name = ''
    sonar_project_key = ''
    jira_project = ''
    cvs_system = 'Git'
    tfs_path = ''
    sub_modules = False
    another_branch = ''
    life_time = ''
    cmake_msbuild = 'CMake'
    select_vcxproj = ''
    pvs_exclude_vcxproj = ''
    pvs_exclude_path = ''
    pvs_check_conf_name = ''
    pvs_check_arch = ''
    cmake_win_commands = ''
    cmake_linux_commands = ''
    disabled = False
    clone_proj = "false"
    edit_proj = "false"
    last_processed_changeset = ''
    version = ''
    disable_jira = True

    # Получение списка проектов Jira с обработкой ошибок
    all_jira_projects = []
    try:
        jira_client = get_jira_client()
        if jira_client is not None:
            all_jira_projects = jira_client.projects()
        else:
            logger.debug("Клиент Jira не доступен, список проектов будет пустым")
            all_jira_projects = []
    except Exception as e:
        logger.error(f"Ошибка получения списка проектов Jira: {e}")
        all_jira_projects = []

    # Обработка клонирования
    if clone_id:
        project = crud.get_project(db, clone_id)
        if project:
            # Заполнение всех полей из проекта, кроме sonar_project_key
            group_id = project.group_id
            author_email = project.author_email
            sonar_project_name = project.sonar_project_name
            sonar_project_key = ""  # Очистка для клонирования
            jira_project = project.jira_project
            cvs_system = project.cvs_system
            tfs_path = project.tfs_path
            sub_modules = project.sub_modules
            another_branch = project.another_branch
            life_time = project.life_time
            cmake_msbuild = project.cmake_msbuild
            select_vcxproj = project.select_vcxproj
            pvs_exclude_vcxproj = project.pvs_exclude_vcxproj
            pvs_exclude_path = project.pvs_exclude_path
            pvs_check_conf_name = project.pvs_check_conf_name
            pvs_check_arch = project.pvs_check_arch
            cmake_win_commands = project.cmake_win_commands
            cmake_linux_commands = project.cmake_linux_commands
            disabled = project.disabled
            last_processed_changeset = project.last_processed_changeset
            version = project.version
            disable_jira = project.disable_jira
            clone_proj = "true"

    # Обработка редактирования
    elif edit_id:
        project = crud.get_project(db, edit_id)
        if project:
            # Заполнение всех полей из проекта
            group_id = project.group_id
            author_email = project.author_email
            sonar_project_name = project.sonar_project_name
            sonar_project_key = project.sonar_project_key
            jira_project = project.jira_project
            cvs_system = project.cvs_system
            tfs_path = project.tfs_path
            sub_modules = project.sub_modules
            another_branch = project.another_branch
            life_time = project.life_time
            cmake_msbuild = project.cmake_msbuild
            select_vcxproj = project.select_vcxproj
            pvs_exclude_vcxproj = project.pvs_exclude_vcxproj
            pvs_exclude_path = project.pvs_exclude_path
            pvs_check_conf_name = project.pvs_check_conf_name
            pvs_check_arch = project.pvs_check_arch
            cmake_win_commands = project.cmake_win_commands
            cmake_linux_commands = project.cmake_linux_commands
            disabled = project.disabled
            last_processed_changeset = project.last_processed_changeset
            version = project.version
            disable_jira = project.disable_jira
            edit_proj = "true"

    return templates.TemplateResponse("index.html", {
        "request": request,
        "current_date": current_date,
        "group_id": group_id,
        "author_email": author_email,
        "sonar_project_name": sonar_project_name,
        "sonar_project_key": sonar_project_key,
        "jira_project": jira_project,
        "cvs_system": cvs_system,
        "tfs_path": tfs_path,
        "sub_modules": sub_modules,
        "another_branch": another_branch,
        "life_time": life_time,
        "cmake_msbuild": cmake_msbuild,
        "select_vcxproj": select_vcxproj,
        "pvs_exclude_vcxproj": pvs_exclude_vcxproj,
        "pvs_exclude_path": pvs_exclude_path,
        "pvs_check_conf_name": pvs_check_conf_name,
        "pvs_check_arch": pvs_check_arch,
        "cmake_win_commands": cmake_win_commands,
        "cmake_linux_commands": cmake_linux_commands,
        "disabled": disabled,
        "last_processed_changeset": last_processed_changeset,
        "version": version,
        "all_jira_projects": all_jira_projects,
        "disable_jira": disable_jira,
        "clone_proj": clone_proj,
        "edit_proj": edit_proj,
        "edit_id": edit_id,
        "flash_messages": get_flash_messages(request)  # Передаём flash-сообщения
    })


@router.get("/list", response_class=HTMLResponse)
@limiter.limit(RateLimits.PUBLIC_LIST)
async def list_projects(
    request: Request,
    db: Session = Depends(get_db)
):
    # Отобразить список проектов с действиями управления

    # Получение flash-сообщений
    flash_msgs = get_flash_messages(request)

    # Получение всех проектов из базы данных
    projects = crud.get_projects(db)

    # Группировка проектов по группам
    projects_by_group = {}
    for project in projects:
        if project.group not in projects_by_group:
            projects_by_group[project.group] = []
        projects_by_group[project.group].append(project)

    # Сортировка проектов внутри каждой группы по sonar_project_name
    for group in projects_by_group:
        projects_by_group[group] = sorted(
            projects_by_group[group],
            key=lambda x: x.sonar_project_name.lower()  # lower() для регистронезависимой сортировки
        )

    # Проверка статуса администратора
    admin_status = is_admin(request)

    return templates.TemplateResponse(
        "list.html",
        {
            "request": request,
            "projects_by_group": projects_by_group,
            "is_admin": admin_status,
            "client_info": get_client_info(request),
            "flash_messages": flash_msgs  # Передаем сообщения в шаблон
        }
    )
