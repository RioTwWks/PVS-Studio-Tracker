from sqlalchemy.orm import Session
from . import models

import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# Обязательные поля для проекта
REQUIRED_FIELDS = [
    "group_id",
    "author_email",
    "sonar_project_name",
    "sonar_project_key",
    "cvs_system",
    "tfs_path",
    "another_branch",
    "pvs_check_conf_name",
    "pvs_check_arch",
]


# Валидация данных проекта перед созданием/обновлением
def validate_project_data(project_data: dict) -> tuple[bool, str]:
    missing_fields = []

    for field in REQUIRED_FIELDS:
        value = project_data.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            missing_fields.append(field)

    if missing_fields:
        return False, f"Отсутствуют обязательные поля: {', '.join(missing_fields)}"

    # Валидация формата email
    author_email = project_data.get("author_email", "")
    if author_email:
        import re
        email_pattern = r'^[^\s@]+@[^\s@]+\.[^\s@]+$'
        if not re.match(email_pattern, author_email):
            return False, "Неверный формат email (пример: user@example.com)"

    # Валидация системы контроля версий
    cvs_system = project_data.get("cvs_system", "")
    if cvs_system not in ["Git", "TFVC"]:
        return False, "Неверная CVS система (должно быть 'Git' или 'TFVC')"

    # Валидация имени проекта SonarQube (без пробелов)
    sonar_project_name = project_data.get("sonar_project_name", "")
    if sonar_project_name and re.search(r'\s', sonar_project_name):
        return False, "Имя проекта SonarQube не должно содержать пробелы"

    return True, ""


# Получить проект по ID
def get_project(db: Session, project_id: int):
    return db.query(models.Project).filter(models.Project.id == project_id).first()


# Получить список проектов с пагинацией
def get_projects(db: Session, skip: int = 0):
    return db.query(models.Project).offset(skip).all()


# Получить проекты по группе
def get_projects_by_group(db: Session, group_id: str):
    return db.query(models.Project).filter(models.Project.group_id == group_id).all()


# Создать новый проект
def create_project(db: Session, project_data: dict):
    # Сначала очистка пробелов во всех строковых полях
    cleaned_data = {}
    for key, value in project_data.items():
        if isinstance(value, str):
            cleaned_data[key] = value.strip()
        else:
            cleaned_data[key] = value

    # Валидация обязательных полей
    is_valid, error_message = validate_project_data(cleaned_data)
    if not is_valid:
        raise ValueError(error_message)

    try:
        # Создание объекта модели Project из словаря
        db_project = models.Project(
            group_id=cleaned_data.get("group_id"),
            author_email=cleaned_data.get("author_email"),
            sonar_project_name=cleaned_data.get("sonar_project_name"),
            sonar_project_key=cleaned_data.get("sonar_project_key"),
            jira_project=cleaned_data.get("jira_project", ""),
            cvs_system=cleaned_data.get("cvs_system"),
            tfs_path=cleaned_data.get("tfs_path"),
            sub_modules=cleaned_data.get("sub_modules", False),
            another_branch=cleaned_data.get("another_branch", ""),
            life_time=cleaned_data.get("life_time"),
            cmake_msbuild=cleaned_data.get("cmake_msbuild"),
            select_vcxproj=cleaned_data.get("select_vcxproj", ""),
            pvs_exclude_vcxproj=cleaned_data.get("pvs_exclude_vcxproj", ""),
            pvs_exclude_path=cleaned_data.get("pvs_exclude_path", ""),
            pvs_check_conf_name=cleaned_data.get("pvs_check_conf_name"),
            pvs_check_arch=cleaned_data.get("pvs_check_arch"),
            cmake_win_commands=cleaned_data.get("cmake_win_commands", ""),
            cmake_linux_commands=cleaned_data.get("cmake_linux_commands", ""),
            disabled=cleaned_data.get("disabled", False),
            last_processed_changeset=cleaned_data.get("last_processed_changeset", ""),
            version=cleaned_data.get("version", ""),
            disable_jira=cleaned_data.get("disable_jira", True),
        )
        db.add(db_project)
        db.commit()
        db.refresh(db_project)
        logger.info(f"Проект {db_project.sonar_project_name} создан в базе данных")
        return db_project
    except Exception as e:
        db.rollback()
        logger.error(f"Ошибка при создании проекта в базе данных: {e}", exc_info=True)
        raise


# Обновить существующий проект
def update_project(db: Session, project_id: int, project_data: dict):
    # Сначала очистка пробелов во всех строковых полях
    cleaned_data = {}
    for key, value in project_data.items():
        if isinstance(value, str):
            cleaned_data[key] = value.strip()
        else:
            cleaned_data[key] = value

    # Валидация обязательных полей
    is_valid, error_message = validate_project_data(cleaned_data)
    if not is_valid:
        raise ValueError(error_message)

    db_project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if db_project:
        for key, value in cleaned_data.items():
            setattr(db_project, key, value)
        db.commit()
        db.refresh(db_project)
        return db_project
    return None


# Отключить проект
def disable_project(db: Session, project_id: int):
    db_project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if db_project:
        db_project.disabled = True
        db.commit()
        db.refresh(db_project)
    return db_project


# Включить проект
def enable_project(db: Session, project_id: int):
    db_project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if db_project:
        db_project.disabled = False
        db.commit()
        db.refresh(db_project)
    return db_project


# Отключить создание задач Jira для проекта
def disable_jira(db: Session, project_id: int):
    db_project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if db_project:
        db_project.disable_jira = True
        db.commit()
        db.refresh(db_project)
    return db_project


# Включить создание задач Jira для проекта
def enable_jira(db: Session, project_id: int):
    db_project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if db_project:
        db_project.disable_jira = False
        db.commit()
        db.refresh(db_project)
    return db_project


# Удалить проект из базы данных
def delete_project(db: Session, project_id: int):
    db_project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if db_project:
        db.delete(db_project)
        db.commit()
        return True
    return False


# Получить проект по имени
def get_project_by_name(db: Session, project_name: str):
    return db.query(models.Project).filter(models.Project.sonar_project_name == project_name).first()


# Получить проект по ключу SonarQube
def get_project_by_sonar_key(db: Session, sonar_project_key: str):
    return db.query(models.Project).filter(models.Project.sonar_project_key == sonar_project_key).first()


# Получить проекты по пути TFS и ветке
def get_project_by_tfs_path_branch(db: Session, tfs_path: str, another_branch: str):
    return db.query(models.Project).filter(
        models.Project.tfs_path == tfs_path and
        models.Project.another_branch == another_branch
    ).all()


# Функции для работы с файлами и версиями (для scanner API)
def get_or_create_file(db: Session, project, filename: str):
    # Получить файл или создать если не существует
    file_record = db.query(models.File).filter(
        models.File.project_id == project.id,
        models.File.filename == filename
    ).first()

    if not file_record:
        file_record = models.File(project_id=project.id, filename=filename)
        db.add(file_record)
        db.commit()
        db.refresh(file_record)

    return file_record


# Проверить существует ли версия с данным хешем
def get_version_by_hash(db: Session, file_id: int, file_hash: str):
    return db.query(models.Version).filter(
        models.Version.file_id == file_id,
        models.Version.hash == file_hash
    ).first()


# Создать новую версию файла
def create_version(db: Session, file_id: int, version: str, file_hash: str, creation_date: str = None):
    if creation_date is None:
        creation_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    version_record = models.Version(
        file_id=file_id,
        creation_date=creation_date,
        hash=file_hash,
        version=version
    )
    db.add(version_record)
    db.commit()
    db.refresh(version_record)
    return version_record
