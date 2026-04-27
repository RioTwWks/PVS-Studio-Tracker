import json

from sqlmodel import Session, select

from pvs_tracker import main
from pvs_tracker.models import Issue, Project, Run


def make_warning(code, file_path, line, message):
    return {
        "code": code,
        "cwe": 0,
        "level": 1,
        "positions": [
            {
                "file": file_path,
                "line": line,
                "endLine": line,
                "navigation": {
                    "previousLine": 0,
                    "currentLine": 0,
                    "nextLine": 0,
                    "columns": 0,
                },
            }
        ],
        "projects": ["demo"],
        "message": message,
        "favorite": False,
        "falseAlarm": False,
    }


def write_report(path, warnings):
    path.write_text(json.dumps({"version": 3, "warnings": warnings}))


def upload_report(client, path, project_name, commit):
    with path.open("rb") as report:
        return client.post(
            "/api/v1/upload",
            data={"project_name": project_name, "commit": commit, "branch": "main"},
            files={"file": (path.name, report, "application/json")},
        )


def test_first_upload_is_overall_code_baseline(client, tmp_path):
    client.post("/login", data={"username": "alice", "password": "secret"}, follow_redirects=False)

    report_path = tmp_path / "baseline.json"
    write_report(
        report_path,
        [
            make_warning(
                "V501",
                "src/main.cpp",
                42,
                "Identical expressions in 'if' condition.",
            )
        ],
    )

    response = upload_report(client, report_path, "baseline-project", "base")
    assert response.status_code == 200

    with Session(main.engine) as session:
        project = session.exec(select(Project).where(Project.name == "baseline-project")).first()
        assert project is not None
        run = session.exec(select(Run).where(Run.project_id == project.id)).first()
        assert run is not None
        assert run.total_issues == 1
        assert run.new_issues == 0

        issue = session.exec(select(Issue).where(Issue.run_id == run.id)).first()
        assert issue is not None
        assert issue.status == "existing"


def test_later_upload_marks_only_new_fingerprints_as_new_code(client, tmp_path):
    client.post("/login", data={"username": "alice", "password": "secret"}, follow_redirects=False)

    baseline_warning = make_warning(
        "V501",
        "src/main.cpp",
        42,
        "Identical expressions in 'if' condition.",
    )
    new_warning = make_warning(
        "V502",
        "src/second.cpp",
        7,
        "Perhaps the '?:' operator works in a different way than it was expected.",
    )

    baseline_path = tmp_path / "baseline.json"
    second_path = tmp_path / "second.json"
    write_report(baseline_path, [baseline_warning])
    write_report(second_path, [baseline_warning, new_warning])

    response = upload_report(client, baseline_path, "new-code-project", "base")
    assert response.status_code == 200
    response = upload_report(client, second_path, "new-code-project", "next")
    assert response.status_code == 200

    with Session(main.engine) as session:
        project = session.exec(select(Project).where(Project.name == "new-code-project")).first()
        assert project is not None
        runs = session.exec(
            select(Run).where(Run.project_id == project.id).order_by(Run.timestamp.asc())
        ).all()
        assert len(runs) == 2
        assert runs[0].total_issues == 1
        assert runs[0].new_issues == 0
        assert runs[1].total_issues == 2
        assert runs[1].new_issues == 1

        second_issues = session.exec(select(Issue).where(Issue.run_id == runs[1].id)).all()
        statuses = {issue.rule_code: issue.status for issue in second_issues}
        assert statuses["V501"] == "existing"
        assert statuses["V502"] == "new"
