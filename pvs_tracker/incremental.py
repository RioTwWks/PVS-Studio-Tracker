from sqlmodel import Session, select

from pvs_tracker.issue_author import resolve_issue_author
from pvs_tracker.models import ErrorClassifier, GlobalSettings, Issue, Project, Run
from pvs_tracker.platforms import compute_cross_platform_fp
from pvs_tracker.security import calculate_technical_debt


def _get_prev_run(session: Session, project_id: int, run: Run) -> Run | None:
    """Previous successful run for the same target platform (excludes current run)."""
    return session.exec(
        select(Run)
        .where(
            Run.project_id == project_id,
            Run.status == "done",
            Run.target_platform == run.target_platform,
            Run.id != run.id,
        )
        .order_by(Run.timestamp.desc())
        .limit(1),
    ).first()


def _build_issue(
    run_id: int,
    iss: dict,
    status: str,
    classifier_id: int | None,
    tech_debt: int,
    line_val: int,
    col_val: int,
    end_line_val: int,
    end_col_val: int,
    cwe_val: int | None,
    cross_fp: str,
    author_name: str | None,
    author_email: str | None,
) -> Issue:
    return Issue(
        run_id=run_id,
        fingerprint=iss["fingerprint"],
        cross_platform_fp=cross_fp,
        file_path=iss["file_path"],
        line=line_val,
        rule_code=iss["rule_code"],
        severity=iss["severity"],
        message=iss["message"],
        status=status,
        classifier_id=classifier_id,
        column=col_val,
        end_line=end_line_val,
        end_column=end_col_val,
        cwe_id=cwe_val,
        technical_debt_minutes=tech_debt,
        author_name=author_name,
        author_email=author_email,
    )


def classify_and_store(
    session: Session,
    project_id: int,
    run_id: int,
    new_issues: list[dict],
) -> None:
    """Compare fingerprints against the previous successful run and classify."""
    run = session.get(Run, run_id)
    if not run:
        raise ValueError(f"Run {run_id} not found")

    project = session.get(Project, project_id)
    global_settings = session.exec(select(GlobalSettings).where(GlobalSettings.id == 1)).first()

    prev_run = _get_prev_run(session, project_id, run)

    prev_fps: set[str] = set()
    if prev_run:
        prev_issues = session.exec(select(Issue).where(Issue.run_id == prev_run.id)).all()
        prev_fps = {i.fingerprint for i in prev_issues if i.status not in ("ignored", "fixed")}

    classifiers = session.exec(select(ErrorClassifier)).all()
    code_to_classifier = {c.rule_code: c for c in classifiers}

    platform = run.target_platform or "windows"
    current_fps: set[str] = set()
    for iss in new_issues:
        current_fps.add(iss["fingerprint"])
        iss["status"] = "existing" if not prev_run or iss["fingerprint"] in prev_fps else "new"

        rule_code = iss.get("rule_code", "")
        classifier = code_to_classifier.get(rule_code)
        classifier_id = classifier.id if classifier else None

        severity = iss.get("severity", "Medium")
        priority = classifier.priority if classifier else "MAJOR"
        remediation = classifier.remediation_effort if classifier else 5
        tech_debt = calculate_technical_debt(severity, priority, remediation)

        line_val = int(iss["line"]) if isinstance(iss["line"], (int, float)) else 0
        col_val = int(iss.get("column") or 0)
        end_line_val = int(iss.get("end_line") or 0)
        end_col_val = int(iss.get("end_column") or 0)
        cwe_val = iss.get("cwe_id")
        if cwe_val is not None:
            cwe_val = int(cwe_val)
        elif classifier:
            cwe_val = classifier.cwe_id

        cross_fp = compute_cross_platform_fp(
            iss["file_path"],
            iss["rule_code"],
            iss["message"],
            project=project,
            global_settings=global_settings,
            platform=platform,  # type: ignore[arg-type]
        )

        author_name, author_email = resolve_issue_author(
            session,
            run,
            iss["status"],
            iss["fingerprint"],
            prev_run,
        )

        session.add(
            _build_issue(
                run_id,
                iss,
                iss["status"],
                classifier_id,
                tech_debt,
                line_val,
                col_val,
                end_line_val,
                end_col_val,
                cwe_val,
                cross_fp,
                author_name,
                author_email,
            )
        )

    if prev_run:
        fixed_fps = prev_fps - current_fps
        for fp in fixed_fps:
            prev_issue = session.exec(
                select(Issue).where(Issue.fingerprint == fp, Issue.run_id == prev_run.id)
            ).first()
            if prev_issue and prev_issue.status not in ("ignored", "fixed"):
                author_name, author_email = resolve_issue_author(
                    session,
                    run,
                    "fixed",
                    fp,
                    prev_run,
                    prev_issue=prev_issue,
                )
                session.add(
                    Issue(
                        run_id=run_id,
                        fingerprint=prev_issue.fingerprint,
                        cross_platform_fp=prev_issue.cross_platform_fp,
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
                        technical_debt_minutes=0,
                        author_name=author_name,
                        author_email=author_email,
                    )
                )

    session.commit()


def add_issues_to_existing_run(
    session: Session,
    project_id: int,
    run_id: int,
    new_issues: list[dict],
) -> int:
    """Добавляет проблемы из дополнительного отчёта в существующий Run той же платформы."""
    run = session.get(Run, run_id)
    if not run or run.status != "done":
        raise ValueError("Run must exist and be in 'done' state")

    project = session.get(Project, project_id)
    global_settings = session.exec(select(GlobalSettings).where(GlobalSettings.id == 1)).first()
    platform = run.target_platform or "windows"

    prev_run = _get_prev_run(session, project_id, run)

    prev_fps: set[str] = set()
    if prev_run:
        prev_issues = session.exec(select(Issue).where(Issue.run_id == prev_run.id)).all()
        prev_fps = {i.fingerprint for i in prev_issues if i.status not in ("ignored", "fixed")}

    classifiers = session.exec(select(ErrorClassifier)).all()
    code_to_classifier = {c.rule_code: c for c in classifiers}

    existing_fps_in_run = {
        i.fingerprint for i in session.exec(select(Issue).where(Issue.run_id == run_id)).all()
    }

    added_new = 0
    for iss in new_issues:
        fp = iss["fingerprint"]
        if fp in existing_fps_in_run:
            continue

        status = "new" if (prev_run and fp not in prev_fps) else "existing"
        if status == "new":
            added_new += 1

        rule_code = iss.get("rule_code", "")
        classifier = code_to_classifier.get(rule_code)
        classifier_id = classifier.id if classifier else None

        severity = iss.get("severity", "Medium")
        priority = classifier.priority if classifier else "MAJOR"
        remediation = classifier.remediation_effort if classifier else 5
        tech_debt = calculate_technical_debt(severity, priority, remediation)

        line_val = int(iss["line"]) if isinstance(iss.get("line"), (int, float)) else 0
        col_val = int(iss.get("column") or 0)
        end_line_val = int(iss.get("end_line") or 0)
        end_col_val = int(iss.get("end_column") or 0)
        cwe_val = iss.get("cwe_id")
        if cwe_val is not None:
            cwe_val = int(cwe_val)
        elif classifier:
            cwe_val = classifier.cwe_id

        cross_fp = compute_cross_platform_fp(
            iss["file_path"],
            iss["rule_code"],
            iss["message"],
            project=project,
            global_settings=global_settings,
            platform=platform,  # type: ignore[arg-type]
        )

        author_name, author_email = resolve_issue_author(
            session,
            run,
            status,
            fp,
            prev_run,
        )

        session.add(
            _build_issue(
                run_id,
                iss,
                status,
                classifier_id,
                tech_debt,
                line_val,
                col_val,
                end_line_val,
                end_col_val,
                cwe_val,
                cross_fp,
                author_name,
                author_email,
            )
        )

    session.commit()
    return added_new
