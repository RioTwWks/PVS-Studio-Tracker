"""Add CI orchestration columns to existing project/issue tables."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import inspect, text
from sqlmodel import SQLModel

from pvs_tracker.db import engine

logger = logging.getLogger(__name__)

PROJECT_CI_COLUMNS: dict[str, str] = {
    "slug": "VARCHAR",
    "author_email": "VARCHAR",
    "group_name": "VARCHAR",
    "cvs_system": "VARCHAR",
    "repo_path": "VARCHAR",
    "analysis_branch": "VARCHAR DEFAULT ''",
    "jira_project": "VARCHAR DEFAULT ''",
    "sub_modules": "BOOLEAN DEFAULT 0",
    "life_time": "VARCHAR",
    "cmake_msbuild": "VARCHAR",
    "select_vcxproj": "VARCHAR DEFAULT ''",
    "pvs_exclude_vcxproj": "VARCHAR DEFAULT ''",
    "pvs_exclude_path": "VARCHAR DEFAULT ''",
    "pvs_check_conf_name": "VARCHAR",
    "pvs_check_arch": "VARCHAR",
    "cmake_win_commands": "VARCHAR DEFAULT ''",
    "cmake_linux_commands": "VARCHAR DEFAULT ''",
    "disabled": "BOOLEAN DEFAULT 0",
    "disable_jira": "BOOLEAN DEFAULT 1",
    "last_processed_changeset": "VARCHAR DEFAULT ''",
    "release_version": "VARCHAR DEFAULT ''",
    "last_jenkins_build_id": "INTEGER",
    "last_jenkins_build_url": "VARCHAR",
    "last_analysis_at": "DATETIME",
}

ISSUE_CI_COLUMNS: dict[str, str] = {
    "jira_issue_key": "VARCHAR",
}


def _existing_columns(table: str) -> set[str]:
    insp = inspect(engine)
    if table not in insp.get_table_names():
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def _add_columns(table: str, columns: dict[str, str]) -> list[str]:
    existing = _existing_columns(table)
    added: list[str] = []
    with engine.begin() as conn:
        for name, col_type in columns.items():
            if name in existing:
                continue
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {col_type}"))
            added.append(name)
            logger.info("Added column %s.%s", table, name)
    return added


def apply_ci_schema_migration() -> dict[str, Any]:
    """Create missing tables and add CI columns on SQLite/PostgreSQL."""
    SQLModel.metadata.create_all(engine)
    project_added = _add_columns("project", PROJECT_CI_COLUMNS)
    issue_added = _add_columns("issue", ISSUE_CI_COLUMNS)
    return {"project_columns": project_added, "issue_columns": issue_added}
