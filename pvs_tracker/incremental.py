from sqlmodel import Session, select

from pvs_tracker.models import ErrorClassifier, Issue, Run
from pvs_tracker.security import calculate_technical_debt


def classify_and_store(
    session: Session,
    project_id: int,
    run_id: int,
    new_issues: list[dict],
) -> None:
    """Compare fingerprints against the previous successful run and classify."""

    # Find the previous successful run
    prev_run = session.exec(
        select(Run)
        .where(Run.project_id == project_id, Run.status == "done")
        .order_by(Run.timestamp.desc())
        .limit(1),
    ).first()

    prev_fps: set[str] = set()
    if prev_run:
        prev_issues = session.exec(select(Issue).where(Issue.run_id == prev_run.id)).all()
        prev_fps = {i.fingerprint for i in prev_issues if i.status not in ("ignored", "fixed")}

    # Build a map of rule_code -> classifier
    classifiers = session.exec(select(ErrorClassifier)).all()
    code_to_classifier = {c.rule_code: c for c in classifiers}

    current_fps: set[str] = set()
    for iss in new_issues:
        current_fps.add(iss["fingerprint"])
        iss["status"] = "new" if iss["fingerprint"] not in prev_fps else "existing"

        # Link to classifier and calculate technical debt
        rule_code = iss.get("rule_code", "")
        classifier = code_to_classifier.get(rule_code)
        classifier_id = classifier.id if classifier else None

        # Calculate technical debt
        severity = iss.get("severity", "Medium")
        priority = classifier.priority if classifier else "MAJOR"
        remediation = classifier.remediation_effort if classifier else 5
        tech_debt = calculate_technical_debt(severity, priority, remediation)

        issue = Issue(
            run_id=run_id,
            fingerprint=iss["fingerprint"],
            file_path=iss["file_path"],
            line=iss["line"],
            rule_code=iss["rule_code"],
            severity=iss["severity"],
            message=iss["message"],
            status=iss["status"],
            classifier_id=classifier_id,
            column=iss.get("column"),
            end_line=iss.get("end_line"),
            end_column=iss.get("end_column"),
            cwe_id=iss.get("cwe_id") or (classifier.cwe_id if classifier else None),
            technical_debt_minutes=tech_debt,
        )
        session.add(issue)

    # Record disappeared issues as fixed in the *current* run
    if prev_run:
        fixed_fps = prev_fps - current_fps
        for fp in fixed_fps:
            prev_issue = session.exec(
                select(Issue).where(Issue.fingerprint == fp, Issue.run_id == prev_run.id)
            ).first()
            if prev_issue and prev_issue.status not in ("ignored", "fixed"):
                fixed_issue = Issue(
                    run_id=run_id,
                    fingerprint=prev_issue.fingerprint,
                    file_path=prev_issue.file_path,
                    line=prev_issue.line,
                    rule_code=prev_issue.rule_code,
                    severity=prev_issue.severity,
                    message=prev_issue.message,
                    status="fixed",
                    classifier_id=prev_issue.classifier_id,
                    column=prev_issue.column,
                    end_line=prev_issue.end_line,
                    end_column=prev_issue.end_column,
                    cwe_id=prev_issue.cwe_id,
                    technical_debt_minutes=0,  # Fixed issues have no debt
                )
                session.add(fixed_issue)

    session.commit()
