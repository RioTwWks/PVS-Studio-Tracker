import configparser
from pathlib import Path
from sqlalchemy.orm import Session

from . import models, crud

# Мигрирует существующие проекты из файловой системы в базу данных
def migrate_existing_projects(db: Session, logger, PROJECTS_PATH):
    logger.info("Начало миграции проектов из файловой системы")
    migrated_count = 0
    updated_count = 0
    error_count = 0
    base_path = Path(PROJECTS_PATH)

    # Группы проектов из вашего PHP-кода
    groups = ["QAdmin", "QDealer", "QuikFront", "QGates", "QuikServer", "QWeb", "Other_Projects"]

    for group in groups:
        group_path = base_path / group
        if not group_path.exists():
            logger.warning(f"Группа {group} не существует. Пропускаем.")
            continue
        logger.info(f"Обработка группы: {group}")

        # Ищем все файлы execution_task.ini в дереве каталогов
        for ini_file in group_path.rglob("execution_task.ini"):
            # Пропускаем отключенные проекты
            if "_disabled" in str(ini_file):
                logger.info(f"Пропускаем отключенный проект: {ini_file}")
                continue

            try:
                # Определяем путь к проекту относительно группы
                project_relative_path = ini_file.parent.relative_to(group_path)

                # Парсим INI-файл
                config = configparser.ConfigParser()
                config.read(ini_file)

                # Создаем данные проекта до проверки существования
                project_data = {
                    "group_id": group,
                    "author_email": config.get("Configuration", "AUTHOR_EMAIL", fallback=""),
                    "sonar_project_name": str(project_relative_path),
                    "sonar_project_key": config.get("Configuration", "SONAR_PROJECT_KEY", fallback=""),
                    "cvs_system": config.get("Configuration", "CVS_SYSTEM", fallback="Git"),
                    "tfs_path": config.get("Configuration", "TFS_PATH", fallback=""),
                    "sub_modules": config.get("Configuration", "SUB_MODULES", fallback=""),
                    "another_branch": config.get("Configuration", "ANOTHER_BRANCH", fallback=""),
                    "life_time": config.get("Configuration", "LIFE_TIME", fallback=""),
                    "cmake_msbuild": config.get("Configuration", "CMAKE_MSBUILD", fallback="CMake"),
                    "pvs_exclude_vcxproj": config.get("Configuration", "PVS_EXCLUDE_VCXPROJ", fallback=""),
                    "pvs_check_conf_name": config.get("Configuration", "PVS_CHECK_CONF_NAME", fallback=""),
                    "pvs_check_arch": config.get("Configuration", "PVS_CHECK_ARCH", fallback=""),
                }

                # Читаем файлы с командами CMake
                cmake_win_file = ini_file.parent / "cmake_conf.cmd"
                if cmake_win_file.exists():
                    project_data["cmake_win_commands"] = cmake_win_file.read_text(encoding="utf-8", errors="ignore")
                else:
                    project_data["cmake_win_commands"] = ""
                    logger.warning(f"Файл cmake_conf.cmd не найден для проекта {ini_file.parent}")

                cmake_linux_file = ini_file.parent / "cmake_conf.sh"
                if cmake_linux_file.exists():
                    project_data["cmake_linux_commands"] = cmake_linux_file.read_text(encoding="utf-8", errors="ignore")
                else:
                    project_data["cmake_linux_commands"] = ""
                    logger.warning(f"Файл cmake_conf.sh не найден для проекта {ini_file.parent}")

                # Читаем last.changeset
                last_changeset = ini_file.parent / "last.changeset"
                if last_changeset.exists():
                    project_data["last_processed_changeset"] = last_changeset.read_text(encoding="utf-8", errors="ignore")
                else:
                    project_data["last_processed_changeset"] = ""
                    logger.warning(f"Файл last.changeset не найден для проекта {ini_file.parent}")

                # Проверяем существующий проект
                existing_project = db.query(models.Project).filter(
                    models.Project.sonar_project_key == project_data["sonar_project_key"]
                ).first()

                if existing_project:
                    # Обновляем существующий проект
                    for key, value in project_data.items():
                        setattr(existing_project, key, value)
                    logger.info(f"Обновлен проект с ключом {project_data['sonar_project_key']}")
                    updated_count += 1
                else:
                    # Создаем новый проект
                    crud.create_project(db, project_data)
                    logger.info(f"Добавлен проект: {group}/{project_relative_path} (key: {project_data['sonar_project_key']})")
                    migrated_count += 1

            except Exception as e:
                logger.error(f"Ошибка при обработке файла {ini_file}: {e}")
                error_count += 1

    logger.info(f"Миграция завершена. Добавлено: {migrated_count}, Обновлено: {updated_count}, Ошибок: {error_count}")
    return migrated_count, updated_count, error_count
