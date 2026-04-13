"""Tests for error classifier functionality."""
import json
import os
import tempfile

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from pvs_tracker import main
from pvs_tracker.models import ErrorClassifier, Project, SQLModel


SAMPLE_REPORT = {
    "version": 3,
    "warnings": [
        {
            "code": "V1001",
            "cwe": 0,
            "level": 1,
            "positions": [
                {
                    "file": "src/test.cpp",
                    "line": 10,
                    "endLine": 10,
                    "navigation": {
                        "previousLine": 0,
                        "currentLine": 0,
                        "nextLine": 0,
                        "columns": 0
                    }
                }
            ],
            "projects": ["demo"],
            "message": "Variable is assigned but not used.",
            "favorite": False,
            "falseAlarm": False
        },
    ],
}


@pytest.fixture(autouse=True)
def setup_db():
    """Recreate tables and load classifiers before each test."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    main.engine.url = f"sqlite:///{tmp.name}"
    SQLModel.metadata.drop_all(main.engine)
    SQLModel.metadata.create_all(main.engine)
    
    # Load classifiers from CSV
    csv_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "Actual_warnings.csv")
    if os.path.exists(csv_path):
        from pvs_tracker.classifier_parser import parse_classifier_csv
        with Session(main.engine) as session:
            classifiers = parse_classifier_csv(csv_path)
            for clf in classifiers:
                session.add(ErrorClassifier(**clf))
            session.commit()
    
    yield
    try:
        os.unlink(tmp.name)
    except:
        pass


@pytest.fixture()
def client():
    os.makedirs("reports", exist_ok=True)
    report_path = "reports/classifier_test.json"
    with open(report_path, "w") as f:
        json.dump(SAMPLE_REPORT, f)
    c = TestClient(main.app)
    yield c


def test_classifiers_loaded(client):
    """Test that error classifiers are loaded from CSV."""
    with Session(main.engine) as session:
        classifiers = session.exec(select(ErrorClassifier)).all()
        assert len(classifiers) > 0
        # Check V1001 is loaded
        v1001 = session.exec(select(ErrorClassifier).where(ErrorClassifier.rule_code == "V1001")).first()
        assert v1001 is not None
        assert v1001.type == "BUG"
        assert v1001.priority == "MAJOR"


def test_issue_linked_to_classifier(client):
    """Test that issues are linked to error classifiers."""
    # Login
    r = client.post("/login", data={"username": "test", "password": "test"}, follow_redirects=False)
    assert r.status_code == 303

    # Upload
    with open("reports/classifier_test.json", "rb") as f:
        r = client.post(
            "/api/v1/upload",
            data={"project_name": "classifier-test", "commit": "abc123", "branch": "main"},
            files={"file": ("classifier_test.json", f, "application/json")},
        )
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "success"
    
    project_id = data["run_id"]

    # Check that issue has classifier_id set
    with Session(main.engine) as session:
        project = session.exec(select(Project).where(Project.name == "classifier-test")).first()
        assert project is not None
        
        # Get the latest run
        from pvs_tracker.models import Issue, Run
        run = session.exec(
            select(Run)
            .where(Run.project_id == project.id, Run.status == "done")
            .order_by(Run.timestamp.desc())
            .limit(1)
        ).first()
        assert run is not None
        
        issues = session.exec(select(Issue).where(Issue.run_id == run.id)).all()
        assert len(issues) == 1
        assert issues[0].classifier_id is not None
        
        # Verify the classifier linkage
        classifier = session.get(ErrorClassifier, issues[0].classifier_id)
        assert classifier is not None
        assert classifier.rule_code == "V1001"
        assert classifier.priority == "MAJOR"


def test_dashboard_includes_classifier_summary(client):
    """Test that dashboard API includes classifier summary."""
    # Login and upload
    client.post("/login", data={"username": "test", "password": "test"}, follow_redirects=False)
    
    with open("reports/classifier_test.json", "rb") as f:
        r = client.post(
            "/api/v1/upload",
            data={"project_name": "summary-test", "commit": "abc123", "branch": "main"},
            files={"file": ("classifier_test.json", f, "application/json")},
        )
    
    project_id = r.json()["run_id"]
    
    # Get dashboard
    r = client.get(f"/api/v1/projects/{project_id}/dashboard")
    assert r.status_code == 200
    data = r.json()
    
    assert "classifier_summary" in data
    summary = data["classifier_summary"]
    assert "total_rules" in summary
    assert summary["total_rules"] > 0
    assert "by_type" in summary
    assert "by_priority" in summary


def test_ui_issues_shows_classifier_info(client):
    """Test that issues UI shows classifier type and priority."""
    # Login and upload
    client.post("/login", data={"username": "test", "password": "test"}, follow_redirects=False)
    
    with open("reports/classifier_test.json", "rb") as f:
        r = client.post(
            "/api/v1/upload",
            data={"project_name": "ui-classifier-test", "commit": "abc123", "branch": "main"},
            files={"file": ("classifier_test.json", f, "application/json")},
        )
    
    with Session(main.engine) as session:
        project = session.exec(select(Project).where(Project.name == "ui-classifier-test")).first()
        assert project is not None
        project_id = project.id
    
    # Get issues page
    r = client.get(f"/ui/issues?project_id={project_id}")
    assert r.status_code == 200
    
    # Should show classifier info
    assert "BUG" in r.text
    assert "MAJOR" in r.text
