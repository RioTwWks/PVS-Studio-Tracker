"""Secure file path resolution with path traversal protection."""

import logging
import os
import platform
from pathlib import Path
from typing import Optional

from fastapi import HTTPException

from pvs_tracker.models import GlobalSettings

logger = logging.getLogger(__name__)


def get_os_type() -> str:
    """Detect current OS type ('windows' or 'linux')."""
    system = platform.system()
    return "windows" if system == "Windows" else "linux"


def resolve_source_path(
    project_source_root_win: str | None,
    project_source_root_linux: str | None,
    report_file_path: str,
    os_type: Optional[str] = None,
) -> Path:
    """
    Safely convert a path from a PVS report to an absolute server path.
    Detects OS automatically and uses the corresponding source root.
    """
    import logging
    logger = logging.getLogger("pvs_tracker")
    
    # Detect OS and select appropriate source root
    if os_type:
        source_root = project_source_root_win if os_type == "windows" else project_source_root_linux
    else:
        # старое поведение: определяем ОС сервера
        os_type_detected = get_os_type()
        source_root = project_source_root_win if os_type_detected == "windows" else project_source_root_linux

    if not source_root:
        raise HTTPException(
            400,
            f"source_root_{os_type or get_os_type()} is not configured..."
        )

    base = Path(source_root).resolve()

    # 🔑 БЕЗОПАСНАЯ нормализация пути
    # 1. Декодируем URL если нужно
    if "%" in report_file_path:
        from urllib.parse import unquote
        norm_path = unquote(report_file_path)
    else:
        norm_path = report_file_path
    
    # 2. Заменяем все возможные варианты разделителей на ос-специфичные
    #    Но НЕ превращаем \ в \t!
    norm_path = norm_path.strip()
    
    # 3. Если путь абсолютный, пробуем извлечь относительную часть
    if Path(norm_path).is_absolute():
        # Нормализуем для сравнения
        norm_for_compare = norm_path.replace("\\", "/").lower()
        base_for_compare = str(base).replace("\\", "/").lower()
        
        # Пробуем убрать префикс базы
        if norm_for_compare.startswith(base_for_compare):
            # Убираем префикс базы
            relative = norm_path[len(str(base)):]
            if relative.startswith(("\\", "/")):
                relative = relative[1:]
            norm_path = relative
        else:
            # Fallback: используем только имя файла если не удалось сопоставить
            logger.warning("Absolute path not mapped to base, using basename: %s", norm_path)
            norm_path = Path(norm_path).name

    # 🔑 КРИТИЧЕСКИ ВАЖНО: проверяем на опасные символы ПЕРЕД созданием пути
    if ".." in norm_path or "\t" in norm_path or "\n" in norm_path or "\r" in norm_path:
        logger.error("Invalid path characters detected in: %s", repr(norm_path))
        raise HTTPException(403, "Invalid path characters detected")
    
    # Создаём целевой путь
    target = (base / norm_path).resolve()

    # Strict check: resolved path must be under base directory
    if not str(target).startswith(str(base) + os.sep) and str(target) != str(base):
        logger.error("Path traversal blocked: %s vs %s", target, base)
        raise HTTPException(403, "Path traversal blocked")

    if not target.exists():
        logger.warning("File not found: %s", target)
        raise HTTPException(404, f"File not found: {target}")
    if not target.is_file():
        raise HTTPException(400, "Path is not a file")

    return target


def get_effective_source_root(
    project_source_root_win: Optional[str],
    project_source_root_linux: Optional[str],
    global_settings: Optional["GlobalSettings"] = None,
) -> Optional[str]:
    """
    Возвращает эффективный source root:
    1. Если задан в проекте — используем его
    2. Иначе — используем глобальный дефолт
    3. Иначе — None
    """
    os_type = get_os_type()
    project_root = project_source_root_win if os_type == "windows" else project_source_root_linux
    
    if project_root:
        return project_root
    
    if global_settings:
        global_root = (
            global_settings.default_source_root_win 
            if os_type == "windows" 
            else global_settings.default_source_root_linux
        )
        return global_root
    
    return None

def normalize_file_path_for_display(
    file_path: str,
    source_root: Optional[str],
) -> str:
    """
    Нормализует путь для отображения: убирает префикс source_root.
    Пример: 
        file_path = "D:\\temp\\DL_lib\\dl_lib\\src\\TLogWriter.cpp"
        source_root = "D:\\temp\\DL_lib"
        → результат: "dl_lib\\src\\TLogWriter.cpp"
    """
    if not source_root:
        return file_path
    
    # Нормализуем разделители
    norm_file = file_path.replace("\\", "/").lstrip("/")
    norm_root = source_root.replace("\\", "/").rstrip("/")
    
    # Убираем префикс (регистронезависимо для кроссплатформенности)
    if norm_file.lower().startswith(norm_root.lower()):
        # Убираем префикс + возможный слэш
        relative = norm_file[len(norm_root):].lstrip("/")
        if relative:
            return relative
    
    # Если не удалось убрать префикс — возвращаем как есть
    return file_path
