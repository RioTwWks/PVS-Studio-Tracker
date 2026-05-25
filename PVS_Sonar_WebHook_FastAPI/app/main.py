"""
Главная точка входа приложения

Веб-сервис на FastAPI для управления проектами статического анализа кода (PVS-Studio + SonarQube).
Автоматизирует жизненный цикл анализа кода: от коммитов в TFVC/Git до создания задач в Jira.
"""

import os
from fastapi import FastAPI, Depends, HTTPException
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from . import models
from .database import engine, get_db, SessionLocal
from .logging_config import setup_logging, get_logger

# Импорт роутеров
from .routers import pages, projects
from .webhooks import handle_webhook, health_check as webhook_health_check
from .sonarqube_webhook import handle_sonarqube_webhook, sonarqube_health_check

# Инициализация логирования
setup_logging(
    log_level='INFO',
    log_dir='logs',
    retention_days=30,
    console_output=True
)

logger = get_logger(__name__)

# Инициализация таблиц базы данных
models.Base.metadata.create_all(bind=engine)

# Создание приложения FastAPI
app = FastAPI(
    title="PVS+Sonar Project Manager",
    description="Веб-сервис для управления проектами статического анализа кода",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Инициализация rate limiting (ленивый импорт)
def setup_rate_limiting():
    # Настройка middleware rate limiting
    from .rate_limiter import limiter, rate_limit_exceeded_handler
    app.state.limiter = limiter
    app.add_exception_handler(Exception, rate_limit_exceeded_handler)
    return app.state.limiter

# Настройка rate limiting
setup_rate_limiting()

# Подключение статических файлов
app.mount("/static", StaticFiles(directory="static"), name="static")

# Подключение директории .well-known (для расширения Chrome DevTools)
app.mount("/.well-known", StaticFiles(directory=".well-known"), name="well-known")

# Регистрация роутеров
app.include_router(pages.router)
app.include_router(projects.router)

# Регистрация endpoint'ов веб-хуков
app.add_api_route("/webhook", handle_webhook, methods=["POST"], tags=["webhooks"])
app.add_api_route("/webhook/health", webhook_health_check, methods=["GET"], tags=["health"])

# Регистрация endpoint'ов SonarQube веб-хуков
app.add_api_route("/sonarqube-webhook", handle_sonarqube_webhook, methods=["POST"], tags=["webhooks", "sonarqube"])
app.add_api_route("/sonarqube-webhook/health", sonarqube_health_check, methods=["GET"], tags=["health"])


# Миграция существующих проектов из файловой системы в базу данных
@app.get("/migrate-projects", tags=["admin"])
async def migrate_projects(db: Session = Depends(get_db)):
    """
    Эндпоинт следует вызвать один раз при начальной настройке для импорта проектов из legacy файлового хранилища.
    """
    from .migrate import migrate_existing_projects

    logger.info("Запуск миграции проектов через эндпоинт /migrate-projects")

    try:
        source_path = os.getenv("SOURCE_PATH", "D:\\SAST\\PVS_Sonar_WebHook_FastAPI\\source")
        projects_path = f"{source_path}\\Projects"

        migrated_count, skipped_count, error_count = migrate_existing_projects(
            db,
            logger,
            projects_path
        )
        db.commit()

        logger.info(f"Миграция завершена: {migrated_count} мигрировано, {skipped_count} пропущено, {error_count} ошибок")

        return {
            "message": "Миграция проектов успешно завершена",
            "migrated": migrated_count,
            "skipped": skipped_count,
            "errors": error_count
        }
    except Exception as e:
        db.rollback()
        logger.error(f"Ошибка миграции: {str(e)}", exc_info=True)
        return {"error": f"Миграция не удалась: {str(e)}"}


# Эндпоинт проверки работоспособности приложения
@app.get("/health", tags=["health"])
async def health_check():
    return {
        "status": "healthy",
        "service": "pvs-sonar-project-manager",
        "version": "2.0.0"
    }


# Предоставляем доступ к файлу конфигурации Chrome DevTools
@app.get("/.well-known/appspecific/com.chrome.devtools.json", tags=["config"])
async def serve_chrome_devtools_config():
    # Эндпоинт для конфигурации Chrome DevTools
    try:
        file_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            ".well-known",
            "appspecific",
            "com.chrome.devtools.json"
        )

        if os.path.exists(file_path):
            from fastapi.responses import FileResponse
            return FileResponse(file_path, media_type="application/json")
        else:
            # Если файла нет, создаем конфигурацию на лету
            config = {
                "name": "PVS+Sonar Project Manager",
                "description": "Web interface for managing PVS Studio and SonarQube projects",
                "version": "1.0.0",
                "type": "web",
                "categories": ["development", "code quality"],
                "icons": {
                    "16": "/static/ico.png",
                    "48": "/static/ico.png",
                    "128": "/static/ico.png"
                },
                "permissions": [
                    "tabs",
                    "activeTab",
                    "http://qube/",
                    "http://localhost:8000/"
                ],
                "manifest_version": 2
            }
            from fastapi.responses import JSONResponse
            return JSONResponse(content=config)
    except Exception as e:
        logger.error(f"Error serving Chrome DevTools config: {e}")
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=500,
            content={"error": "Internal server error"}
        )


# Эндпоинт для приёма результатов сканирования от scanner.py
@app.post("/api/scan-results", tags=["scanner"])
async def receive_scan_results(scan_result: dict):
    """
    Принять результаты сканирования от scanner.py.

    Scanner.py запускается через планировщик задач и отправляет результаты через этот endpoint.

    Ожидаемый формат:
    {
        "files": [
            {
                "project_key": "project.key",
                "filename": "file.dll",
                "version": "1.0.0.0",
                "file_hash": "abc123..."
            }
        ]
    }
    """
    from . import crud

    logger.info(f"📥 Получены результаты сканирования: {len(scan_result.get('files', []))} файлов")

    try:
        db = SessionLocal()
        try:
            # Обработка каждого файла
            for file_data in scan_result.get("files", []):
                project_key = file_data.get("project_key")
                filename = file_data.get("filename")
                version = file_data.get("version")
                file_hash = file_data.get("file_hash")

                if not all([project_key, filename, version, file_hash]):
                    logger.warning(f"Неполные данные для файла: {file_data}")
                    continue

                # Поиск проекта в БД
                project = crud.get_project_by_sonar_key(db, project_key)
                if not project:
                    logger.warning(f"Проект {project_key} не найден. Пропускаем файл {filename}")
                    continue

                # Поиск файла в БД
                file_record = crud.get_or_create_file(db, project, filename)

                # Проверка дубликата по хешу
                existing = crud.get_version_by_hash(db, file_record.id, file_hash)
                if existing:
                    logger.debug(f"Версия с хэшем {file_hash} уже существует для {filename}")
                    continue

                # Сохранение новой версии
                crud.create_version(db, file_record.id, version, file_hash)
                logger.info(f"✅ Добавлена версия {version} для {filename}")

            logger.info(f"✅ Результаты сканирования успешно обработаны")

        finally:
            db.close()

        return {"status": "success", "message": f"Processed {len(scan_result.get('files', []))} files"}

    except Exception as e:
        logger.error(f"Ошибка обработки результатов сканирования: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# Событие запуска
@app.on_event("startup")
async def startup_event():
    # Логирование запуска приложения
    logger.info(
        "PVS+Sonar Project Manager запускается",
        extra={"repo_type": "SYSTEM", "repo_name": "STARTUP"}
    )


# Событие остановки
@app.on_event("shutdown")
async def shutdown_event():
    # Логирование остановки приложения
    try:
        logger.info(
            "PVS+Sonar Project Manager останавливается",
            extra={"repo_type": "SYSTEM", "repo_name": "SHUTDOWN"}
        )
    except Exception:
        pass  # Игнорировать ошибки во время остановки
