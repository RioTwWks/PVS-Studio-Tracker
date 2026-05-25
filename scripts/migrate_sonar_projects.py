"""
Migrate projects from PVS_Sonar_WebHook_FastAPI SQLite DB into PVS-Studio Tracker.

Usage:
    python scripts/migrate_sonar_projects.py --source PVS_Sonar_WebHook_FastAPI/pvs_sonar.db
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlmodel import Session, select

from pvs_tracker.db import engine
from pvs_tracker.db_migrate_ci import apply_ci_schema_migration
from pvs_tracker.models import Project
from pvs_tracker.project_ci import get_project_by_name, slug_from_name

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def migrate(source_db: Path) -> None:
    if not source_db.is_file():
        raise FileNotFoundError(source_db)

    apply_ci_schema_migration()
    conn = sqlite3.connect(source_db)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute(
        """
        SELECT p.*, g.internal_name AS group_name
        FROM projects p
        LEFT JOIN groups g ON p.group_id = g.id
        """
    )
    rows = cur.fetchall()
    created = merged = 0

    with Session(engine) as session:
        for row in rows:
            name = row["sonar_project_name"]
            existing = get_project_by_name(session, name)
            fields = {
                "slug": row["sonar_project_key"],
                "author_email": row["author_email"],
                "group_name": row["group_name"] or "Ungrouped",
                "cvs_system": row["cvs_system"],
                "repo_path": row["tfs_path"],
                "analysis_branch": row["another_branch"] or "",
                "jira_project": row["jira_project"] or "",
                "sub_modules": bool(row["sub_modules"]),
                "life_time": row["life_time"],
                "cmake_msbuild": row["cmake_msbuild"],
                "select_vcxproj": row["select_vcxproj"] or "",
                "pvs_exclude_vcxproj": row["pvs_exclude_vcxproj"] or "",
                "pvs_exclude_path": row["pvs_exclude_path"] or "",
                "pvs_check_conf_name": row["pvs_check_conf_name"],
                "pvs_check_arch": row["pvs_check_arch"],
                "cmake_win_commands": row["cmake_win_commands"] or "",
                "cmake_linux_commands": row["cmake_linux_commands"] or "",
                "disabled": bool(row["disabled"]),
                "disable_jira": bool(row["disable_jira"]),
                "last_processed_changeset": row["last_processed_changeset"] or "",
                "release_version": row["version"] or "",
            }
            if existing:
                for key, val in fields.items():
                    setattr(existing, key, val)
                session.add(existing)
                merged += 1
            else:
                slug = fields.pop("slug") or slug_from_name(name)
                project = Project(name=name, language="c++", slug=slug, **fields)
                session.add(project)
                created += 1
        session.commit()

    logger.info("Migration done: created=%s merged=%s total_source=%s", created, merged, len(rows))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source",
        default=str(ROOT / "PVS_Sonar_WebHook_FastAPI" / "pvs_sonar.db"),
        help="Path to legacy pvs_sonar.db",
    )
    args = parser.parse_args()
    migrate(Path(args.source))


if __name__ == "__main__":
    main()
