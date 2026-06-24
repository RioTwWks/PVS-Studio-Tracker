"""Quality gate evaluation engine (rule-code sets)."""

from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime
from typing import Any

from sqlmodel import Session, select

from sqlalchemy.exc import IntegrityError

from pvs_tracker.models import (
    ErrorClassifier,
    Issue,
    Project,
    QualityGate,
    QualityGateRule,
    Run,
)

logger = logging.getLogger(__name__)


def resolve_project_quality_gate(session: Session, project: Project) -> QualityGate | None:
    """Return gate assigned to project or the default gate."""
    if project.quality_gate_id:
        gate = session.get(QualityGate, project.quality_gate_id)
        if gate:
            return gate
    return session.exec(
        select(QualityGate).where(QualityGate.is_default == True)  # noqa: E712
    ).first()


def get_gate_rule_codes(session: Session, gate_id: int) -> set[str]:
    rows = session.exec(
        select(QualityGateRule.rule_code).where(QualityGateRule.quality_gate_id == gate_id)
    ).all()
    return set(rows)


def set_gate_rules(session: Session, gate_id: int, rule_codes: list[str]) -> None:
    """Replace all rules for a gate."""
    existing = session.exec(
        select(QualityGateRule).where(QualityGateRule.quality_gate_id == gate_id)
    ).all()
    for row in existing:
        session.delete(row)
    session.flush()
    for code in sorted(set(rule_codes)):
        session.add(QualityGateRule(quality_gate_id=gate_id, rule_code=code))
    gate = session.get(QualityGate, gate_id)
    if gate:
        gate.updated_at = datetime.utcnow()
        session.add(gate)
    session.commit()


def populate_default_gate_rules(session: Session, gate_id: int) -> int:
    """Assign all catalog rule codes to the default gate."""
    codes = session.exec(select(ErrorClassifier.rule_code)).all()
    if not codes:
        return 0
    set_gate_rules(session, gate_id, list(codes))
    return len(codes)


def evaluate_quality_gate(session: Session, project_id: int, run_id: int) -> dict[str, Any]:
    """Evaluate quality gate: failed if any NEW issue has rule_code in gate scope."""
    project = session.get(Project, project_id)
    if not project:
        return {
            "status": "failed",
            "error": "Project not found",
            "conditions": [],
            "summary": {},
        }

    quality_gate = resolve_project_quality_gate(session, project)
    if not quality_gate or quality_gate.id is None:
        return {
            "status": "passed",
            "conditions": [],
            "summary": {"passed": 0, "failed": 0, "total": 0, "new_in_gate": 0},
        }

    gate_rules = get_gate_rule_codes(session, quality_gate.id)
    if not gate_rules:
        return {
            "status": "passed",
            "gate_id": quality_gate.id,
            "gate_name": quality_gate.name,
            "conditions": [],
            "summary": {
                "passed": 0,
                "failed": 0,
                "total": 0,
                "new_in_gate": 0,
                "total_rules_in_gate": 0,
            },
        }

    issues = session.exec(select(Issue).where(Issue.run_id == run_id)).all()
    scoped_new = [i for i in issues if i.status == "new" and i.rule_code in gate_rules]

    counts = Counter(i.rule_code for i in scoped_new)
    evaluated_conditions = [
        {
            "rule_code": code,
            "new_count": count,
            "status": "failed",
        }
        for code, count in sorted(counts.items())
    ]

    overall_status = "failed" if scoped_new else "passed"
    if overall_status == "passed":
        evaluated_conditions = []

    return {
        "status": overall_status,
        "gate_id": quality_gate.id,
        "gate_name": quality_gate.name,
        "conditions": evaluated_conditions,
        "summary": {
            "passed": 0 if scoped_new else 1,
            "failed": 1 if scoped_new else 0,
            "total": 1,
            "new_in_gate": len(scoped_new),
            "failed_rules": len(counts),
            "total_rules_in_gate": len(gate_rules),
        },
    }


def calculate_run_metrics(session: Session, run_id: int) -> dict[str, Any]:
    """Calculate all metrics for a specific run (dashboard ratings)."""
    issues = session.exec(select(Issue).where(Issue.run_id == run_id)).all()

    new_issues = [i for i in issues if i.status == "new"]
    fixed_issues = [i for i in issues if i.status == "fixed"]
    active_issues = [i for i in issues if i.status in ("new", "existing")]
    ignored_issues = [i for i in issues if i.status == "ignored"]

    high_issues = [i for i in active_issues if i.severity == "High"]
    critical_issues = [
        i for i in active_issues if i.severity == "High" and i.rule_code.startswith("V")
    ]

    active_count = len(active_issues)
    if active_count == 0:
        reliability_rating = "A"
    elif active_count <= 10:
        reliability_rating = "B"
    elif active_count <= 30:
        reliability_rating = "C"
    elif active_count <= 100:
        reliability_rating = "D"
    else:
        reliability_rating = "E"

    security_issues = [
        i for i in active_issues if i.classifier and i.classifier.type == "SECURITY"
    ]
    security_count = len(security_issues)
    if security_count == 0:
        security_rating = "A"
    elif security_count <= 5:
        security_rating = "B"
    elif security_count <= 20:
        security_rating = "C"
    elif security_count <= 50:
        security_rating = "D"
    else:
        security_rating = "E"

    if active_count == 0:
        maintainability_rating = "A"
    elif active_count <= 10:
        maintainability_rating = "B"
    elif active_count <= 30:
        maintainability_rating = "C"
    elif active_count <= 100:
        maintainability_rating = "D"
    else:
        maintainability_rating = "E"

    total_debt_minutes = sum(i.technical_debt_minutes for i in active_issues)

    return {
        "new_issues": len(new_issues),
        "fixed_issues": len(fixed_issues),
        "active_issues": active_count,
        "total_issues": len(issues),
        "ignored_issues": len(ignored_issues),
        "high_issues": len(high_issues),
        "critical_issues": len(critical_issues),
        "reliability_rating": reliability_rating,
        "security_rating": security_rating,
        "maintainability_rating": maintainability_rating,
        "technical_debt_minutes": total_debt_minutes,
        "security_issues": security_count,
    }


def create_default_quality_gate(session: Session) -> QualityGate:
    """Create default quality gate with all catalog rule codes."""
    existing = session.exec(
        select(QualityGate).where(QualityGate.is_default == True)  # noqa: E712
    ).first()
    if not existing:
        existing = session.exec(
            select(QualityGate).where(QualityGate.name == "Default Quality Gate")
        ).first()
    if existing:
        if existing.id is not None:
            rule_count = len(get_gate_rule_codes(session, existing.id))
            if rule_count == 0:
                populate_default_gate_rules(session, existing.id)
        return existing

    gate = QualityGate(name="Default Quality Gate", is_default=True)
    session.add(gate)
    try:
        session.commit()
        session.refresh(gate)
    except IntegrityError:
        session.rollback()
        existing = session.exec(
            select(QualityGate).where(QualityGate.name == "Default Quality Gate")
        ).first()
        if existing:
            return existing
        raise

    if gate.id is not None:
        populate_default_gate_rules(session, gate.id)

    return gate
