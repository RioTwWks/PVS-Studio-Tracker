"""Code viewer route for inline source display with warning annotations.

Supports multiple source retrieval strategies:
1. Git repository (SonarQube-style, no server-side code storage)
2. Source archive (uploaded zip/tar)
3. Local filesystem (legacy, backward compatibility)
"""

import asyncio
import functools
from pathlib import Path, PurePosixPath
from typing import Optional, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select, func

from pvs_tracker.db import get_session
from pvs_tracker.git_integration import fetch_source_file
from pvs_tracker.models import ErrorClassifier, Issue, Project, Run, GlobalSettings
from pvs_tracker.file_resolver import (  # 🔑 Для нормализации путей
    get_effective_source_root,
    normalize_file_path_for_display,
)

router = APIRouter()

# Module-level templates reference (set in main.py after app init)
templates: Optional[Jinja2Templates] = None

# Правила, которые не привязаны к файлам (аналитические/системные)
# Источник: https://files.pvs-studio.com/rules/RulesMap.xml
ANALYSIS_ONLY_RULES = frozenset([
    "V010",  # Analysis for project type/platform toolsets not supported
    "V011",  # Compiler monitoring mode issues
    "V012",  # Task scheduler / parallel analysis issues
    "V013",  # License issues
    "V014",  # Update check issues
    "V015",  # Preprocessor errors (global)
    "V016",  # Configuration file errors
    "V017",  # Internal analyzer errors
    "V018",  # Resource exhaustion warnings
    "V019",  # Timeout warnings
    "V020",  # Unsupported compiler/version warnings
    "V021",  # Platform mismatch warnings
])


def _extract_file_name(file_path: str) -> str:
    """Extract file name from path (works with both / and \\ separators)."""
    # Normalize to forward slashes for consistent parsing
    normalized = file_path.replace("\\", "/")
    return PurePosixPath(normalized).name


# File reading cache with mtime-based invalidation
@functools.lru_cache(maxsize=256)
def _read_file_cached(abs_path_str: str, mtime: float) -> list[str]:
    """Read file lines with mtime-based cache invalidation."""
    with open(abs_path_str, encoding="utf-8", errors="replace") as f:
        return f.readlines()


def _read_file_with_cache(abs_path: Path) -> list[str]:
    """Read file with automatic caching based on modification time."""
    stat = abs_path.stat()
    return _read_file_cached(str(abs_path), stat.st_mtime)


@router.get("/ui/file", response_class=HTMLResponse)
async def view_code(
    request: Request,
    project_id: int = Query(..., ge=1),
    file_path: str = Query(...),
    line: int = Query(None, ge=1),
    run_id: int = Query(None, ge=1),
    context: int = Query(0, ge=0),  # 🔑 Добавлен параметр context
    session: Session = Depends(get_session),
):
    """Display source file with inline warning annotations."""
    if templates is None:
        raise HTTPException(500, "Templates not initialized")

    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    # Get commit from run if available
    commit = None
    if run_id:
        run = session.get(Run, run_id)
        if run:
            commit = run.commit
    else:
        run = session.exec(
            select(Run)
            .where(Run.project_id == project_id, Run.status == "done")
            .order_by(Run.timestamp.desc())
            .limit(1)
        ).first()
        if run:
            commit = run.commit

    # Fetch source file using fallback strategy
    lines = []
    error = None
    source_type = "unavailable"

    try:
        source_file = await fetch_source_file(
            project_id=project_id,
            file_path=file_path,
            run_id=run.id if run else None,
            git_url=project.git_url,
            git_branch=project.git_branch,
            commit=commit,
            source_archive_path=project.source_archive_path,
            source_root_win=project.source_root_win,
            source_root_linux=project.source_root_linux,
        )
        lines = source_file.lines
        source_type = source_file.source
    except HTTPException as exc:
        error = str(exc.detail)
    except Exception as exc:
        error = f"Error reading file: {exc}"

    # Обработка context ПОСЛЕ чтения файла
    line_offset = 0
    # Гарантируем, что target_display_line не None
    target_display_line = None
    if line and line_offset is not None:
        target_display_line = line - line_offset
    
    if context > 0 and line:
        total_file_lines = len(lines)
        # line — это номер строки с предупреждением (1-based)
        start_idx = max(0, line - context - 1)
        end_idx = min(total_file_lines, line + context)
        
        lines = lines[start_idx:end_idx]
        line_offset = start_idx
        target_display_line = line - line_offset  # Корректируем номер для подсветки
    else:
        line_offset = 0
        target_display_line = line

    #  Правильное объединение строк
    content = "".join(lines)
    total_lines = len(lines)

    #  Detect language for Prism.js
    lang = "cpp"
    if file_path:
        ext = file_path.rsplit(".", 1)[-1].lower() if "." in file_path else ""
        lang_map = {
            "cpp": "cpp", "cc": "cpp", "cxx": "cpp", "h": "cpp", "hpp": "cpp",
            "c": "c", "cs": "csharp", "java": "java", "py": "python",
            "js": "javascript", "ts": "typescript", "json": "json",
        }
        lang = lang_map.get(ext, "cpp")

    # Determine run & warnings
    if run_id:
        run = session.get(Run, run_id)
    else:
        run = session.exec(
            select(Run).where(Run.project_id == project_id, Run.status == "done")
            .order_by(Run.timestamp.desc()).limit(1)
        ).first()

    # Build warnings by line mapping (filtered by current visible range)
    warnings_by_line = {}
    classifier_map = {}
    if run:
        issues = session.exec(
            select(Issue).where(
                Issue.run_id == run.id,
                Issue.file_path == file_path.replace("\\", "/"),
                Issue.status.in_(["new", "existing"]),
            )
        ).all()

        # Fetch classifiers for lookup
        classifier_ids = {i.classifier_id for i in issues if i.classifier_id}
        if classifier_ids:
            classifiers = session.exec(select(ErrorClassifier).where(ErrorClassifier.id.in_(classifier_ids))).all()
            classifier_map = {c.id: c for c in classifiers}

        # 🔑 Фильтруем предупреждения только для видимого диапазона строк
        visible_start = line_offset + 1
        visible_end = line_offset + total_lines
        for issue in issues:
            if visible_start <= issue.line <= visible_end:
                # Сдвигаем номер строки для отображения относительно offset
                display_line = issue.line - line_offset
                warnings_by_line.setdefault(display_line, []).append(issue)

    return templates.TemplateResponse(
        request,
        "code_view.html",
        {
            "project": project,
            "file_path": file_path,
            "file_name": _extract_file_name(file_path),
            "content": content,
            "language": lang,
            "warnings_by_line": warnings_by_line,
            "target_line": target_display_line,  # Может быть None, но шаблон теперь это обрабатывает
            "run_id": run.id if run else None,
            "error": error,
            "classifier_map": classifier_map,
            "source_type": source_type,
            "line_offset": line_offset,
            "total_lines": total_lines,
        },
    )


@router.get("/ui/projects/{project_id}/code-viewer", response_class=HTMLResponse)
async def code_viewer_page(
    request: Request,
    project_id: int,
    run_id: int = Query(None, ge=1),
    session: Session = Depends(get_session),
):
    """Standalone code viewer page with file browser."""
    if templates is None:
        raise HTTPException(500, "Templates not initialized")
    
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    # Determine which run to use
    if run_id:
        run = session.get(Run, run_id)
    else:
        run = session.exec(
            select(Run)
            .where(Run.project_id == project_id, Run.status == "done")
            .order_by(Run.timestamp.desc())
            .limit(1)
        ).first()

    # Get files with warnings
    files_with_warnings = []
    warnings_by_line_global = {}  # 🔑 Для глобальной статистики
    
    if run:
        # Get distinct file paths with warning counts
        file_counts = session.exec(
            select(Issue.file_path, func.count(Issue.id))
            .where(
                Issue.run_id == run.id,
                Issue.status.in_(["new", "existing"]),
            )
            .group_by(Issue.file_path)
            .order_by(func.count(Issue.id).desc())
        ).all()

        files_with_warnings = [
            {"file_path": file_path, "warning_count": count}
            for file_path, count in file_counts
        ]
        
        # 🔑 Build global warnings_by_line for stats (all files)
        issues = session.exec(
            select(Issue).where(
                Issue.run_id == run.id,
                Issue.status.in_(["new", "existing"]),
            )
        ).all()
        for issue in issues:
            if issue.line not in warnings_by_line_global:
                warnings_by_line_global[issue.line] = []
            warnings_by_line_global[issue.line].append(issue)

    return templates.TemplateResponse(
        request,
        "code_viewer_page.html",
        {
            "project": project,
            "files_with_warnings": files_with_warnings,
            "run_id": run.id if run else None,
            # 🔑 Передаём глобальные данные для статистики
            "warnings_by_line": warnings_by_line_global,
            "total_issues": len(warnings_by_line_global),
        },
    )

@router.get("/api/projects/{project_id}/files")
async def get_project_files_api(
    project_id: int,
    run_id: Optional[int] = Query(None),
    session: Session = Depends(get_session),
):
    """Get file tree structure for project with warning counts."""
    import logging
    logger = logging.getLogger("pvs_tracker")
    logger.info(f"🔍 get_project_files_api called: project_id={project_id}, run_id={run_id}")
    
    # 🔑 Получаем проект для доступа к настройкам source_root
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    
    # Получаем глобальные настройки
    global_settings = session.exec(select(GlobalSettings).where(GlobalSettings.id == 1)).first()

    # Determine which run to use
    if run_id:
        run = session.get(Run, run_id)
        logger.info(f"🔍 Using explicit run_id={run_id}, run={run}")
    else:
        run = session.exec(
            select(Run)
            .where(Run.project_id == project_id, Run.status == "done")
            .order_by(Run.timestamp.desc())
            .limit(1)
        ).first()
        logger.info(f"🔍 Auto-selected run={run}")
    
    if not run:
        logger.warning(f"⚠️ No run found for project {project_id}")
        return {"files": [], "total_files": 0, "run_id": None}
    
    # Get distinct files with warning counts and severities
    file_stats = session.exec(
        select(Issue.file_path, func.count(Issue.id), func.max(Issue.severity))
        .where(Issue.run_id == run.id, Issue.status.in_(["new", "existing"]))
        .group_by(Issue.file_path)
    ).all()
    
    logger.info(f"🔍 Found {len(file_stats)} files with warnings")
    
    # 🔑 Фильтруем "аналитические" правила, не привязанные к файлам
    filtered_stats = []
    for file_path, count, max_sev in file_stats:
        # Пропускаем синтетические пути (__analysis__/VXXX)
        if file_path.startswith("__analysis__/"):
            continue
        # Пропускаем правила из списка ANALYSIS_ONLY_RULES
        rule_code = file_path.split("/")[-1] if "/" in file_path else file_path
        if rule_code in ANALYSIS_ONLY_RULES:
            continue
        filtered_stats.append((file_path, count, max_sev))

    # 🔑 Нормализуем пути для отображения
    effective_root = get_effective_source_root(
        project.source_root_win,
        project.source_root_linux,
        global_settings,
    )

    file_tree: dict = {}
    for file_path, count, max_sev in filtered_stats:
        # 🔑 Нормализуем путь для дерева
        display_path = normalize_file_path_for_display(file_path, effective_root)
        
        parts = display_path.replace("\\", "/").split("/")
        current = file_tree
        for part in parts[:-1]:
            if part not in current:
                current[part] = {"_type": "folder", "_children": {}}
            current = current[part]["_children"]
        filename = parts[-1]
        current[filename] = {
            "_type": "file",
            "name": filename,
            "path": file_path,          # Оригинал для fetch
            "display_path": display_path,  # Для отображения в дереве
            "warnings": count,
            "severity": max_sev or "Low",
        }

    # Convert tree to list with children
    def tree_to_list(tree: dict) -> list:
        result = []
        for name, data in tree.items():
            if data["_type"] == "folder":
                children = tree_to_list(data["_children"])
                folder_warnings = sum(
                    f["warnings"] for f in data["_children"].values() 
                    if f["_type"] == "file"
                )
                folder_warnings += sum(
                    c.get("total_warnings", 0) for c in children
                )
                result.append({
                    "name": name,
                    "type": "folder",
                    "path": name,
                    "children": children,
                    "total_warnings": folder_warnings,
                })
            else:
                result.append(data)
        return result

    files_list = tree_to_list(file_tree)
    
    result = {
        "files": files_list,
        "total_files": len(files_list),
        "run_id": run.id,
    }
    logger.info(f"✅ Returning {len(files_list)} items")
    return result


@router.get("/ui/projects/{project_id}/files/search")
async def search_project_files(
    project_id: int,
    q: str = Query("", max_length=100),
    run_id: Optional[int] = Query(None),
    request: Request = None,
    session: Session = Depends(get_session),
):
    """HTMX endpoint: return filtered file tree HTML."""
    if not q:
        # Return full tree
        return await get_project_files_api(project_id, run_id, session)
    
    # Simple in-memory filter
    files_data = await get_project_files_api(project_id, run_id, session)
    filtered = [
        f for f in files_data.get("files", [])
        if q.lower() in f.get("name", "").lower() or q.lower() in f.get("path", "").lower()
    ]
    
    # Return partial HTML for HTMX
    from fastapi.templating import Jinja2Templates
    templates = Jinja2Templates(directory="pvs_tracker/templates")
    return templates.TemplateResponse(
        request,
        "partials/file_tree_partial.html",  # Создайте этот шаблон или верните JSON
        {"files": filtered}
    )


def flatten_files(files: List[Dict]):
    """Helper to count all files recursively."""
    for f in files:
        if f["type"] == "file":
            yield f
        else:
            yield from flatten_files(f.get("children", []))
