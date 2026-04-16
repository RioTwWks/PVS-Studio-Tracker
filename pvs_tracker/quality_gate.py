"""Quality gate evaluation engine."""

from typing import Any
from sqlmodel import Session, select

from pvs_tracker.models import Issue, QualityGate, QualityGateCondition, Run

import logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("pvs_tracker.qa")

# ---------------------------------------------------------------------------
# Quality gate evaluation
# ---------------------------------------------------------------------------

OPERATORS = {
    "gt": lambda a, b: a > b,
    "gte": lambda a, b: a >= b,
    "lt": lambda a, b: a < b,
    "lte": lambda a, b: a <= b,
    "eq": lambda a, b: a == b,
    "ne": lambda a, b: a != b,
}


def evaluate_quality_gate(session: Session, project_id: int, run_id: int) -> dict[str, Any]:
    """Evaluate quality gate conditions for a specific run.

    Returns:
        {
            "status": "passed" | "failed",
            "conditions": [
                {"metric": "...", "operator": "...", "threshold": N, "actual": M, "status": "passed" | "failed"},
                ...
            ],
            "summary": {"passed": N, "failed": M, "total": K}
        }
    """
    # Get the project's quality gate (or default)
    from pvs_tracker.models import Project
    project = session.get(Project, project_id)
    if not project:
        return {"status": "failed", "error": "Project not found", "conditions": [], "summary": {}}

    quality_gate = None
    if project.quality_gate_id:
        quality_gate = session.get(QualityGate, project.quality_gate_id)
    if not quality_gate:
        # Use default gate
        quality_gate = session.exec(
            select(QualityGate).where(QualityGate.is_default == True)
        ).first()
    if not quality_gate:
        # No gate configured - pass by default
        return {"status": "passed", "conditions": [], "summary": {"passed": 0, "failed": 0, "total": 0}}

    # Get conditions
    conditions = session.exec(
        select(QualityGateCondition).where(QualityGateCondition.quality_gate_id == quality_gate.id)
    ).all()

    # Calculate metrics for this run
    metrics = calculate_run_metrics(session, run_id)

    # Evaluate each condition
    evaluated_conditions = []
    for condition in conditions:
        actual_value = metrics.get(condition.metric, 0)
        operator_func = OPERATORS.get(condition.operator)
        if not operator_func:
            continue

        # Check if condition passes (condition passes when operator(actual, threshold) is False for error conditions)
        # For quality gates, we want: if actual violates threshold, it fails
        # For example: "new_issues gt 0" means fail if new_issues > 0
        # 🔒 Явное приведение типов перед сравнением
        try:
            actual_val = int(actual_value) if isinstance(actual_value, (int, float)) else 0
            threshold_val = int(condition.threshold) if isinstance(condition.threshold, (int, float)) else 0
            condition_failed = operator_func(actual_val, threshold_val)
        except (ValueError, TypeError) as e:
            logger.warning(f"Quality gate comparison failed for {condition.metric}: {e}")
            condition_failed = False

        evaluated_conditions.append({
            "metric": condition.metric,
            "operator": condition.operator,
            "threshold": threshold_val,
            "actual": actual_val,
            "status": "failed" if condition_failed else "passed",
            "error_policy": condition.error_policy,
        })

    # Determine overall status
    failed_conditions = [c for c in evaluated_conditions if c["status"] == "failed" and c["error_policy"] == "error"]
    overall_status = "failed" if failed_conditions else "passed"

    return {
        "status": overall_status,
        "conditions": evaluated_conditions,
        "summary": {
            "passed": len([c for c in evaluated_conditions if c["status"] == "passed"]),
            "failed": len([c for c in evaluated_conditions if c["status"] == "failed"]),
            "total": len(evaluated_conditions),
        },
    }


def calculate_run_metrics(session: Session, run_id: int) -> dict[str, Any]:
    """Calculate all metrics for a specific run."""
    issues = session.exec(select(Issue).where(Issue.run_id == run_id)).all()

    # Count issues by status and severity
    new_issues = [i for i in issues if i.status == "new"]
    fixed_issues = [i for i in issues if i.status == "fixed"]
    active_issues = [i for i in issues if i.status in ("new", "existing")]
    ignored_issues = [i for i in issues if i.status == "ignored"]

    high_issues = [i for i in active_issues if i.severity == "High"]
    critical_issues = [i for i in active_issues if i.severity == "High" and i.rule_code.startswith(("V",))]

    # Calculate reliability rating (based on active issues)
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

    # Calculate security rating (based on SECURITY type issues)
    security_issues = [i for i in active_issues if i.classifier and i.classifier.type == "SECURITY"]
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

    # Calculate maintainability rating (all active issues)
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

    # Calculate technical debt
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
    """Create a default quality gate with standard conditions."""
    # Check if default gate already exists
    existing = session.exec(
        select(QualityGate).where(QualityGate.is_default == True)
    ).first()
    if existing:
        return existing

    gate = QualityGate(name="Default Quality Gate", is_default=True)
    session.add(gate)
    session.commit()
    session.refresh(gate)

    # Add standard conditions
    default_conditions = [
        QualityGateCondition(
            quality_gate_id=gate.id,
            metric="new_issues",
            operator="gt",
            threshold=0,
            error_policy="error",
        ),
        QualityGateCondition(
            quality_gate_id=gate.id,
            metric="reliability_rating",
            operator="lt",
            threshold=3,  # C or worse fails
            error_policy="warn",
        ),
    ]

    for condition in default_conditions:
        session.add(condition)
    session.commit()

    return gate
