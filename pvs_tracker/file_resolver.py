"""Secure file path resolution with path traversal protection."""

import logging
import os
import platform
from pathlib import Path

from fastapi import HTTPException

logger = logging.getLogger(__name__)


def get_os_type() -> str:
    """Detect current OS type ('windows' or 'linux')."""
    system = platform.system()
    return "windows" if system == "Windows" else "linux"


def resolve_source_path(
    project_source_root_win: str | None,
    project_source_root_linux: str | None,
    report_file_path: str,
) -> Path:
    """
    Safely convert a path from a PVS report to an absolute server path.
    Detects OS automatically and uses the corresponding source root.
    """
    # Detect OS and select appropriate source root
    os_type = get_os_type()
    if os_type == "windows":
        source_root = project_source_root_win
    else:
        source_root = project_source_root_linux

    if not source_root:
        raise HTTPException(
            400,
            f"source_root_{os_type} is not configured for this project. "
            f"Please set it in Project Settings.",
        )

    base = Path(source_root).resolve()

    # Normalize the path from the report
    norm_path = report_file_path.replace("\\", "/").strip()

    # If the path is absolute, try to extract a relative portion
    if Path(norm_path).is_absolute():
        # Try to strip known CI/CD prefixes
        for prefix in ["/build", "/src", "/workspace", "C:\\", "/home", "C:/"]:
            if norm_path.lower().startswith(prefix.lower()):
                norm_path = norm_path[len(prefix) :].lstrip("/\\")
                break
        else:
            # Fallback: use just the basename
            logger.warning("Absolute path not mapped, using basename: %s", norm_path)
            norm_path = Path(norm_path).name

    target = (base / norm_path).resolve()

    # Strict check: resolved path must be under base directory
    if not str(target).startswith(str(base) + os.sep) and str(target) != str(base):
        raise HTTPException(403, "Path traversal blocked")

    if not target.exists():
        raise HTTPException(404, f"File not found: {target}")
    if not target.is_file():
        raise HTTPException(400, "Path is not a file")

    return target
