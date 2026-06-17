"""Tests for incremental vs full report upload scope."""

import json

import pytest
from fastapi import HTTPException
from sqlmodel import Session, select

from pvs_tracker.db import engine
from pvs_tracker.incremental import classify_and_store
from pvs_tracker.models import Issue, Project, Run
from pvs_tracker.platforms import normalize_report_type


def _issue(fp: str, code: str = "V1001") -> dict:
    return {
        "fingerprint": fp,
        "file_path": "src/a.cpp",
        "line": 10,
        "rule_code": code,
        "severity": "High",
        "message": f"warning {fp}",
    }


def _seed_done_run(session: Session, project: Project, *, commit: str = "c1") -> Run:
    run = Run(
        project_id=project.id,
        commit=commit,
        branch="main",
        target_platform="windows",
        report_file="db:first.json",
        status="done",
        report_type="incremental",
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    classify_and_store(session, project.id, run.id, [_issue("fp-a"), _issue("fp-b")], report_type="full")
    run.status = "done"
    session.add(run)
    session.commit()
    return run


def test_normalize_report_type_defaults_and_valid() -> None:
    assert normalize_report_type(None) == "incremental"
    assert normalize_report_type("FULL") == "full"
    assert normalize_report_type("incremental") == "incremental"


def test_normalize_report_type_invalid() -> None:
    with pytest.raises(HTTPException) as exc:
        normalize_report_type("partial")
    assert exc.value.status_code == 400


def test_incremental_upload_does_not_mark_fixed() -> None:
    with Session(engine) as session:
        project = Project(name="report-type-inc")
        session.add(project)
        session.commit()
        session.refresh(project)
        _seed_done_run(session, project)

        run2 = Run(
            project_id=project.id,
            commit="c2",
            branch="main",
            target_platform="windows",
            report_file="db:second.json",
            status="processing",
            report_type="incremental",
        )
        session.add(run2)
        session.commit()
        session.refresh(run2)

        classify_and_store(
            session,
            project.id,
            run2.id,
            [_issue("fp-a")],
            report_type="incremental",
        )

        issues = session.exec(select(Issue).where(Issue.run_id == run2.id)).all()
        statuses = {i.fingerprint: i.status for i in issues}
        assert statuses == {"fp-a": "existing"}
        assert "fp-b" not in statuses


def test_full_upload_marks_missing_as_fixed() -> None:
    with Session(engine) as session:
        project = Project(name="report-type-full")
        session.add(project)
        session.commit()
        session.refresh(project)
        _seed_done_run(session, project)

        run2 = Run(
            project_id=project.id,
            commit="c2",
            branch="main",
            target_platform="windows",
            report_file="db:second.json",
            status="processing",
            report_type="full",
        )
        session.add(run2)
        session.commit()
        session.refresh(run2)

        classify_and_store(
            session,
            project.id,
            run2.id,
            [_issue("fp-a")],
            report_type="full",
        )

        issues = session.exec(select(Issue).where(Issue.run_id == run2.id)).all()
        statuses = {i.fingerprint: i.status for i in issues}
        assert statuses["fp-a"] == "existing"
        assert statuses["fp-b"] == "fixed"


def test_parse_metadata_report_type() -> None:
    from pvs_tracker.upload_metadata import parse_commit_metadata_bytes

    raw = json.dumps({"report_type": "full", "commit": "abc"}).encode()
    assert parse_commit_metadata_bytes(raw)["report_type"] == "full"
