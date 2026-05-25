"""
Роутеры управления проектами.

CRUD операции для проектов: создание, обновление, клонирование, включение/выключение, удаление.
"""

from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import RedirectResponse
from fastapi import Response
import os
from sqlalchemy.orm import Session
from typing import Optional

from app import crud
from app.database import get_db
from app.logging_config import get_logger
from app.rate_limiter import limiter, RateLimits
from app.sonarqube_api_client import sonarqube_client, sonarqube_client_token
from app.webhooks import trigger_jenkins_job
from app.email_utils import send_email
from app.admin_utils import get_client_info, is_admin
from app.services.repository_service import get_head_commit_git, get_latest_changeset_tfvc

logger = get_logger(__name__)

# Импортируем flash-сообщения из pages.py (общее хранилище)
from app.routers.pages import add_flash_message as add_flash_msg

# Добавляет flash-сообщение в cookies
def add_flash_message(response: Response, message: str, category: str = "success"):
    return add_flash_msg(response, message, category)


router = APIRouter(prefix="/project", tags=["projects"])


@router.post("")
@limiter.limit(RateLimits.PUBLIC_FORM)
async def create_or_update_project(
    request: Request,
    group_id: str = Form(...),
    author_email: str = Form(...),
    sonar_project_name: str = Form(...),
    sonar_project_key: str = Form(...),
    jira_project: str = Form(""),
    cvs_system: str = Form(...),
    tfs_path: str = Form(...),
    sub_modules: bool = Form(False),
    another_branch: str = Form(""),
    life_time: Optional[str] = Form(""),
    cmake_msbuild: Optional[str] = Form(""),
    select_vcxproj: str = Form(""),
    pvs_exclude_vcxproj: Optional[str] = Form(""),
    pvs_exclude_path: Optional[str] = Form(""),
    pvs_check_conf_name: str = Form(...),
    pvs_check_arch: str = Form(...),
    cmake_win_commands: str = Form(""),
    cmake_linux_commands: str = Form(""),
    disabled: bool = Form(False),
    last_processed_changeset: Optional[str] = Form(""),
    version: Optional[str] = Form(""),
    disable_jira: bool = Form(True),
    edit_id: Optional[str] = Form(""),
    db: Session = Depends(get_db)
):
    # Создать или обновить проект
    try:
        # Преобразование edit_id в int если предоставлен
        edit_id_int = None
        if edit_id is not None and edit_id.strip() != "":
            try:
                edit_id_int = int(edit_id)
            except ValueError:
                raise HTTPException(status_code=400, detail="Неверный edit_id")

        project_data = {
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
            "disable_jira": disable_jira,
        }

        if edit_id_int is not None:
            # Обновление существующего проекта
            project = crud.update_project(db, edit_id_int, project_data)
            message = "Проект обновлён"
        else:
            # Создание нового проекта
            project = crud.create_project(db, project_data)

            # Создание в SonarQube
            branch_name = another_branch.split("/")[-1] if another_branch else "main"
            sonarqube_client.create_sq_project(
                f"{project.sonar_project_key}_{branch_name}",
                f"{project.sonar_project_name}_{branch_name}",
                another_branch
            )
            logger.info(f"Создан проект: {project.sonar_project_name}_{branch_name} с веткой {another_branch}")
            message = "Проект создан"

        # Отправка email только для новых проектов
        if edit_id_int is None:
            subject = f"Новый проект '{project.sonar_project_name}' в PVS+SonarQube"
            body = (
                f"Проект {project.sonar_project_name} был добавлен через форму.\n"
                f"Выполните эту команду в PowerShell на QUBE:\n"
                f"{os.getcwd()}\\webhook_scripts\\get_id.ps1 \"{project.sonar_project_name}\" \"{project.cvs_system}\" \"{project.group}\" \"{project.tfs_path}\" \"{project.another_branch}\""
            )
            send_email(subject, body)

        logger.info(message)

        response = RedirectResponse(url="/list", status_code=303)
        add_flash_message(response, "Проект успешно сохранён", "success")
        return response

    except Exception as e:
        logger.error(f"Ошибка сохранения проекта: {e}", exc_info=True)
        response = RedirectResponse(url="/", status_code=303)
        add_flash_message(response, f"Ошибка при сохранении проекта: {str(e)}", "error")
        return response


# Клонировать существующий проект
@router.post("/clone/{project_id}")
@limiter.limit(RateLimits.PUBLIC_FORM)
async def clone_project(
    request: Request,
    project_id: int,
    db: Session = Depends(get_db)
):
    try:
        original_project = crud.get_project(db, project_id)
        if not original_project:
            raise HTTPException(status_code=404, detail="Проект не найден")

        new_project_data = {
            "group_id": original_project.group_id,
            "author_email": original_project.author_email,
            "sonar_project_name": f"{original_project.sonar_project_name}_clone",
            "sonar_project_key": f"{original_project.sonar_project_key}.clone",
            "jira_project": original_project.jira_project,
            "cvs_system": original_project.cvs_system,
            "tfs_path": original_project.tfs_path,
            "sub_modules": original_project.sub_modules,
            "another_branch": original_project.another_branch,
            "life_time": original_project.life_time,
            "cmake_msbuild": original_project.cmake_msbuild,
            "select_vcxproj": original_project.select_vcxproj,
            "pvs_exclude_vcxproj": original_project.pvs_exclude_vcxproj,
            "pvs_exclude_path": original_project.pvs_exclude_path,
            "pvs_check_conf_name": original_project.pvs_check_conf_name,
            "pvs_check_arch": original_project.pvs_check_arch,
            "cmake_win_commands": original_project.cmake_win_commands,
            "cmake_linux_commands": original_project.cmake_linux_commands,
            "disabled": False,
            "last_processed_changeset": original_project.last_processed_changeset,
            "version": original_project.version,
            "disable_jira": True,
        }

        new_project = crud.create_project(db, new_project_data)

        logger.info(f"Клонирован проект {original_project.sonar_project_name} как {new_project.sonar_project_name}")

        response = RedirectResponse(url="/list", status_code=303)
        add_flash_message(response, f"Проект {original_project.sonar_project_name} успешно клонирован", "success")
        return response

    except Exception as e:
        logger.error(f"Ошибка клонирования проекта: {e}", exc_info=True)
        response = RedirectResponse(url="/list", status_code=303)
        add_flash_message(response, f"Ошибка клонирования: {str(e)}", "error")
        return response


# Отключить проект
@router.post("/disable/{project_id}")
@limiter.limit(RateLimits.PUBLIC_FORM)
async def disable_project(
    request: Request,
    project_id: int,
    db: Session = Depends(get_db)
):
    try:
        project = crud.disable_project(db, project_id)
        if not project:
            logger.error(f"Ошибка отключения проекта {project_id}")

        response = RedirectResponse(url="/list", status_code=303)
        add_flash_message(response, "Проект успешно отключен", "success")
        return response
    except Exception as e:
        logger.error(f"Ошибка отключения проекта: {e}", exc_info=True)
        response = RedirectResponse(url="/list", status_code=303)
        add_flash_message(response, f"Ошибка при отключении проекта: {str(e)}", "error")
        return response


# Включить проект
@router.post("/enable/{project_id}")
@limiter.limit(RateLimits.PUBLIC_FORM)
async def enable_project(
    request: Request,
    project_id: int,
    db: Session = Depends(get_db)
):
    try:
        project = crud.enable_project(db, project_id)
        if not project:
            logger.error(f"Ошибка включения проекта {project_id}")

        response = RedirectResponse(url="/list", status_code=303)
        add_flash_message(response, "Проект успешно включён", "success")
        return response
    except Exception as e:
        logger.error(f"Ошибка включения проекта: {e}", exc_info=True)
        response = RedirectResponse(url="/list", status_code=303)
        add_flash_message(response, f"Ошибка при включении проекта: {str(e)}", "error")
        return response


# Удалить проект (только администратор)
@router.post("/delete/{project_id}")
@limiter.limit(RateLimits.ADMIN_DELETE)
async def delete_project(
    request: Request,
    project_id: int,
    db: Session = Depends(get_db)
):
    if not is_admin(request):
        raise HTTPException(status_code=403, detail="Доступ запрещён. Только администраторам.")

    try:
        # Получение проекта
        project = crud.get_project(db, project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Проект не найден")

        # Сначала удаление из SonarQube
        sonar_success = sonarqube_client_token.delete_project(project.sonar_project_key)

        if not sonar_success:
            logger.warning(f"Не удалось удалить проект {project.sonar_project_key} из SonarQube, продолжаем локальное удаление")

        # Удаление из базы данных
        crud.delete_project(db, project_id)

        logger.info(f"Проект {project.sonar_project_name} удалён администратором {get_client_info(request)['ip']}")

        response = RedirectResponse(url="/list", status_code=303)
        add_flash_message(response, f"Проект {project.sonar_project_name} успешно удален", "success")
        return response

    except Exception as e:
        logger.error(f"Ошибка удаления проекта: {e}", exc_info=True)
        db.rollback()
        response = RedirectResponse(url="/list", status_code=303)
        add_flash_message(response, f"Ошибка при удалении проекта: {str(e)}", "error")
        return response


# Запустить принудительный анализ для проекта
@router.post("/analyze/{project_id}")
@limiter.limit(RateLimits.ADMIN_ANALYZE)
async def start_analyze(
    request: Request,
    project_id: int,
    db: Session = Depends(get_db)
):
    try:
        project = crud.get_project(db, project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Проект не найден")

        # Определяем является ли это первым сканированием
        # Первое сканирование = отсутствие last_processed_changeset
        has_changeset = bool(project.last_processed_changeset and project.last_processed_changeset.strip())
        first_scan = "YES" if not has_changeset else "NO"

        # Определяем commit_id
        if has_changeset:
            commit_id = project.last_processed_changeset.strip()
        else:
            # Первое сканирование – получаем HEAD / последний changeset
            if project.cvs_system == 'Git':
                commit_id = get_head_commit_git(project)
            elif project.cvs_system == 'TFVC':
                commit_id = get_latest_changeset_tfvc(project)
            else:
                raise HTTPException(status_code=400, detail=f"Неподдерживаемая CVS система: {project.cvs_system}")

            if not commit_id:
                raise HTTPException(
                    status_code=500,
                    detail=f"Не удалось определить HEAD коммит/changeset для проекта {project.sonar_project_name}"
                )

        logger.info(
            f"🚀 ЗАПУЩЕН ПРИНУДИТЕЛЬНЫЙ АНАЛИЗ: "
            f"project_id={project_id}, "
            f"project_name={project.sonar_project_name}, "
            f"sonar_key={project.sonar_project_key}, "
            f"FirstScan={first_scan}, "
            f"LastChangeset={commit_id}, "
            f"initiated_by={request.client.host}"
        )

        trigger_jenkins_job(
            project=project,
            commit_id=commit_id,
            first_scan=first_scan,
            linux_build=True,
            modified_files=[]  # Пустой список = анализ всех файлов
        )

        logger.info(
            f"✅ Принудительный анализ успешно запущен для {project.sonar_project_name}. "
            f"Jenkins получил: FirstScan={first_scan}, COMMIT={commit_id}"
        )

        response = RedirectResponse(url="/list", status_code=303)
        add_flash_message(response, "Анализ проекта успешно запущен", "success")
        return response
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Ошибка запуска принудительного анализа: {e}", exc_info=True)
        response = RedirectResponse(url="/list", status_code=303)
        add_flash_message(response, f"Ошибка запуска анализа: {str(e)}", "error")
        return response


# Обновить версию проекта
@router.post("/version")
async def get_version(
    project_key: str = Form(...),
    project_ver: str = Form(...),
    db: Session = Depends(get_db)
):
    project = crud.get_project_by_sonar_key(db, project_key)
    logger.info(f"project_key = {project_key}, project_ver = {project_ver}, project = {project}, project.version = {project.version}")
    if project:
        project.version = project_ver
        db.commit()
        logger.info(f"Версия проекта {project_key} обновлена на {project_ver}")
        return {
            "status": "success",
            "message": f"Version updated to {project_ver}",
            "project_key": project_key,
            "version": project_ver
        }
    else:
        logger.error(f"Проект {project_key} не найден для обновления версии")
        raise HTTPException(
            status_code=404,
            detail=f"Project with key {project_key} not found"
        )


# Отключить создание задач Jira для проекта
@router.post("/disable_jira/{project_id}")
@limiter.limit(RateLimits.PUBLIC_FORM)
async def disable_jira_tasks(
    request: Request,
    project_id: int,
    db: Session = Depends(get_db)
):
    try:
        project = crud.disable_jira(db, project_id)
        logger.info(f"Создание задач Jira приостановлено: {project}")

        response = RedirectResponse(url="/list", status_code=303)
        add_flash_message(response, "Создание задач в Jira приостановлено", "success")
        return response
    except Exception as e:
        logger.error(f"Ошибка отключения Jira: {e}", exc_info=True)
        response = RedirectResponse(url="/list", status_code=303)
        add_flash_message(response, f"Ошибка: {str(e)}", "error")
        return response


# Включить создание задач Jira для проекта
@router.post("/enable_jira/{project_id}")
@limiter.limit(RateLimits.PUBLIC_FORM)
async def enable_jira_tasks(
    request: Request,
    project_id: int,
    db: Session = Depends(get_db)
):
    try:
        project = crud.enable_jira(db, project_id)
        logger.info(f"Создание задач Jira возобновлено: {project}")

        response = RedirectResponse(url="/list", status_code=303)
        add_flash_message(response, "Создание задач в Jira возобновлено", "success")
        return response
    except Exception as e:
        logger.error(f"Ошибка включения Jira: {e}", exc_info=True)
        response = RedirectResponse(url="/list", status_code=303)
        add_flash_message(response, f"Ошибка: {str(e)}", "error")
        return response


# Обновить commit/changeset проекта
@router.post("/last_commit_changeset")
async def get_last_commit_changeset(
    project_key: str = Form(...),
    commit_changeset: str = Form(...),
    db: Session = Depends(get_db)
):
    project = crud.get_project_by_sonar_key(db, project_key)
    logger.info(f"project_key = {project_key}, commit_changeset = {commit_changeset}, project = {project}, project.last_processed_changeset = {project.last_processed_changeset}")
    if project:
        project.last_processed_changeset = commit_changeset
        db.commit()
        logger.info(f"commit/changeset проекта {project_key} обновлена на {commit_changeset}")
        return {
            "status": "success",
            "message": f"commit/changeset updated to {commit_changeset}",
            "project_key": project_key,
            "last_processed_changeset": commit_changeset
        }
    else:
        logger.error(f"Проект {project_key} не найден для обновления версии")
        raise HTTPException(
            status_code=404,
            detail=f"Project with key {project_key} not found"
        )
