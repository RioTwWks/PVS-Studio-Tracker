"""Integration tests: separate runs per target platform."""

import json

from sqlmodel import Session, select

from pvs_tracker.db import engine
from pvs_tracker.incremental import classify_and_store
from pvs_tracker.models import Project, Run
from pvs_tracker.parser import parse_pvs_report_bytes


SAMPLE_REPORT = {
    "warnings": [
        {
            "file": r"C:\proj\src\a.cpp",
            "line": 10,
            "code": "V1001",
            "message": "Test warning",
            "level": 1,
        }
    ]
}


def test_upload_same_commit_different_platforms_create_two_runs() -> None:
    report_bytes = json.dumps(SAMPLE_REPORT).encode()
    issues = parse_pvs_report_bytes(report_bytes)

    with Session(engine) as session:
        project = Project(name="plat-test-proj")
        session.add(project)
        session.commit()
        session.refresh(project)

        for plat in ("windows", "linux"):
            run = Run(
                project_id=project.id,
                commit="abc",
                branch="main",
                target_platform=plat,
                report_file="db:test.json",
                status="processing",
            )
            session.add(run)
            session.commit()
            session.refresh(run)
            classify_and_store(session, project.id, run.id, issues)
            run.status = "done"
            session.add(run)
            session.commit()

        runs = session.exec(
            select(Run).where(Run.project_id == project.id, Run.commit == "abc")
        ).all()
        platforms = {r.target_platform for r in runs}
        assert platforms == {"windows", "linux"}
        assert len(runs) == 2
