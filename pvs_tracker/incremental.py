from sqlmodel import Session, select

from pvs_tracker.models import Issue, Run


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
        prev_fps = {i.fingerprint for i in prev_issues if i.status != "ignored"}

    current_fps: set[str] = set()
    for iss in new_issues:
        current_fps.add(iss["fingerprint"])
        iss["status"] = "new" if iss["fingerprint"] not in prev_fps else "existing"
        session.add(Issue(run_id=run_id, **iss))

    # Mark disappeared issues as fixed in the previous run
    if prev_run:
        fixed_fps = prev_fps - current_fps
        for fp in fixed_fps:
            fixed_issue = session.exec(
                select(Issue).where(Issue.fingerprint == fp, Issue.run_id == prev_run.id)
            ).first()
            if fixed_issue and fixed_issue.status not in ("ignored",):
                fixed_issue.status = "fixed"

    session.commit()
