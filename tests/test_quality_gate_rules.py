"""Tests for rule-based quality gate evaluation."""

from datetime import datetime

import pytest
from sqlmodel import Session, select

from pvs_tracker import main
from pvs_tracker.models import ErrorClassifier, Issue, Project, QualityGate, Run
from pvs_tracker.quality_gate import (
    evaluate_quality_gate,
    set_gate_rules,
)


@pytest.fixture()
def db_session() -> Session:
    with Session(main.engine) as session:
        yield session


def _ensure_classifier(session: Session, code: str) -> None:
    existing = session.exec(
        select(ErrorClassifier).where(ErrorClassifier.rule_code == code)
    ).first()
    if not existing:
        session.add(
            ErrorClassifier(
                rule_code=code,
                type="BUG",
                priority="MAJOR",
                name=f"Test {code}",
            )
        )
        session.commit()


def test_gate_fails_on_new_issue_in_scope(db_session: Session) -> None:
    _ensure_classifier(db_session, "V1001")
    _ensure_classifier(db_session, "V9999")

    gate = QualityGate(name="Test Gate Scoped", is_default=False)
    db_session.add(gate)
    db_session.commit()
    db_session.refresh(gate)
    assert gate.id is not None
    set_gate_rules(db_session, gate.id, ["V1001"])

    project = Project(name=f"qg-test-{datetime.utcnow().timestamp()}")
    db_session.add(project)
    db_session.commit()
    db_session.refresh(project)
    project.quality_gate_id = gate.id
    db_session.add(project)
    db_session.commit()

    run = Run(project_id=project.id, report_file="t.json", status="done")
    db_session.add(run)
    db_session.commit()
    db_session.refresh(run)

    db_session.add(
        Issue(
            run_id=run.id,
            fingerprint="fp1",
            file_path="a.cpp",
            line=1,
            rule_code="V1001",
            severity="High",
            message="msg",
            status="new",
        )
    )
    db_session.add(
        Issue(
            run_id=run.id,
            fingerprint="fp2",
            file_path="b.cpp",
            line=2,
            rule_code="V9999",
            severity="High",
            message="msg2",
            status="new",
        )
    )
    db_session.commit()

    result = evaluate_quality_gate(db_session, project.id, run.id)
    assert result["status"] == "failed"
    assert result["summary"]["new_in_gate"] == 1
    assert result["conditions"][0]["rule_code"] == "V1001"


def test_gate_passes_when_new_outside_scope(db_session: Session) -> None:
    _ensure_classifier(db_session, "V2001")

    gate = QualityGate(name="Test Gate Narrow", is_default=False)
    db_session.add(gate)
    db_session.commit()
    db_session.refresh(gate)
    assert gate.id is not None
    set_gate_rules(db_session, gate.id, ["V2001"])

    project = Project(name=f"qg-pass-{datetime.utcnow().timestamp()}")
    db_session.add(project)
    db_session.commit()
    db_session.refresh(project)
    project.quality_gate_id = gate.id
    db_session.add(project)
    db_session.commit()

    run = Run(project_id=project.id, report_file="t2.json", status="done")
    db_session.add(run)
    db_session.commit()
    db_session.refresh(run)

    db_session.add(
        Issue(
            run_id=run.id,
            fingerprint="fp3",
            file_path="c.cpp",
            line=3,
            rule_code="V5555",
            severity="High",
            message="out of scope",
            status="new",
        )
    )
    db_session.commit()

    result = evaluate_quality_gate(db_session, project.id, run.id)
    assert result["status"] == "passed"
    assert result["summary"]["new_in_gate"] == 0
