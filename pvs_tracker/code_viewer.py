"""Code viewer route for inline source display with warning annotations."""

import asyncio
import functools
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select, func

from pvs_tracker.db import get_session
from pvs_tracker.file_resolver import resolve_source_path
from pvs_tracker.models import ErrorClassifier, Issue, Project, Run

router = APIRouter()

# Module-level templates reference (set in main.py after app init)
templates: Optional[Jinja2Templates] = None


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
    session: Session = Depends(get_session),
):
    """Display source file with inline warning annotations."""
    if templates is None:
        raise HTTPException(500, "Templates not initialized")

    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    # Resolve file path securely (pass both Windows and Linux roots)
    try:
        abs_path = await asyncio.to_thread(
            resolve_source_path,
            project.source_root_win,
            project.source_root_linux,
            file_path,
        )
        lines = await asyncio.to_thread(_read_file_with_cache, abs_path)
    except HTTPException as exc:
        return templates.TemplateResponse(
            request,
            "code_view.html",
            {
                "project": project,
                "file_path": file_path,
                "abs_path": "",
                "lines": [],
                "warnings_by_line": {},
                "target_line": line,
                "run_id": run_id,
                "error": str(exc.detail),
                "classifier_map": {},
            },
        )
    except Exception as exc:
        return templates.TemplateResponse(
            request,
            "code_view.html",
            {
                "project": project,
                "file_path": file_path,
                "abs_path": "",
                "lines": [],
                "warnings_by_line": {},
                "target_line": line,
                "run_id": run_id,
                "error": f"Error reading file: {exc}",
                "classifier_map": {},
            },
        )

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

    # Build warnings by line mapping
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
            classifiers = session.exec(
                select(ErrorClassifier).where(ErrorClassifier.id.in_(classifier_ids))
            ).all()
            classifier_map = {c.id: c for c in classifiers}

        for issue in issues:
            if issue.line not in warnings_by_line:
                warnings_by_line[issue.line] = []
            warnings_by_line[issue.line].append(issue)

    return templates.TemplateResponse(
        request,
        "code_view.html",
        {
            "project": project,
            "file_path": file_path,
            "abs_path": str(abs_path),
            "lines": lines,
            "warnings_by_line": warnings_by_line,
            "target_line": line,
            "run_id": run.id if run else None,
            "error": None,
            "classifier_map": classifier_map,
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

    return templates.TemplateResponse(
        request,
        "code_viewer_page.html",
        {
            "project": project,
            "files_with_warnings": files_with_warnings,
            "run_id": run.id if run else None,
        },
    )

