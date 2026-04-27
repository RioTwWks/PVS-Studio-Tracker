"""Smoke tests for the MVP."""
import json
import os

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from pvs_tracker import main
from pvs_tracker.models import Project

SAMPLE_REPORT = {
    "version": 3,
    "warnings": [
        {
            "code": "V501",
            "cwe": 0,
            "level": 1,
            "positions": [
                {
                    "file": "src/main.cpp",
                    "line": 42,
                    "endLine": 42,
                    "navigation": {
                        "previousLine": 0,
                        "currentLine": 0,
                        "nextLine": 0,
                        "columns": 0
                    }
                }
            ],
            "projects": ["demo"],
            "message": "Identical expressions in 'if' condition.",
            "favorite": False,
            "falseAlarm": False
        },
    ],
}


@pytest.fixture()
def client():
    os.makedirs("reports", exist_ok=True)
    report_path = "reports/smoke_test.json"
    with open(report_path, "w") as f:
        json.dump(SAMPLE_REPORT, f)
    c = TestClient(main.app)
    yield c


def test_home(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "PVS-Tracker" in r.text


def test_upload_and_dashboard(client):
    # Login
    r = client.post("/login", data={"username": "alice", "password": "secret"}, follow_redirects=False)
    assert r.status_code == 303

    # Upload
    with open("reports/smoke_test.json", "rb") as f:
        r = client.post(
            "/api/v1/upload",
            data={"project_name": "demo", "commit": "abc123", "branch": "main"},
            files={"file": ("smoke_test.json", f, "application/json")},
        )
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "success"
    assert data["total_issues"] == 1
    project_id = data["run_id"]

    # API Dashboard
    r = client.get(f"/api/v1/projects/{project_id}/dashboard")
    assert r.status_code == 200
    dash = r.json()
    assert dash["project"] == "demo"

    # UI Dashboard
    r = client.get(f"/ui/projects/{project_id}/dashboard")
    assert r.status_code == 200
    assert "demo" in r.text

    # Issues
    r = client.get(f"/ui/issues?project_id={project_id}&status_filter=new")
    assert r.status_code == 200
    assert "V501" in r.text


def test_ui_upload_redirects_to_dashboard(client):
    """Test that UI upload redirects to project dashboard instead of returning JSON."""
    # Login
    r = client.post("/login", data={"username": "bob", "password": "secret"}, follow_redirects=False)
    assert r.status_code == 303

    # Upload via UI endpoint
    with open("reports/smoke_test.json", "rb") as f:
        r = client.post(
            "/ui/upload",
            data={"project_name": "ui-test-project", "commit": "def456", "branch": "develop"},
            files={"file": ("smoke_test.json", f, "application/json")},
            follow_redirects=False,
        )
    # Should redirect (303)
    assert r.status_code == 303
    # Check redirect location points to dashboard
    assert "/ui/projects/" in r.headers["location"]
    assert "/dashboard" in r.headers["location"]

    # Follow the redirect
    r = client.get(r.headers["location"])
    assert r.status_code == 200
    assert "ui-test-project" in r.text


def test_first_upload_shows_new_issues(client):
    """Test that first upload shows 'new' issues in the default view.
    
    Regression test: Previously, the default status_filter was 'existing',
    which caused the first upload (where all issues are 'new') to show
    'Предупреждений не найдено' even though issues existed.
    """
    # Login
    r = client.post("/login", data={"username": "alice", "password": "secret"}, follow_redirects=False)
    assert r.status_code == 303

    # Upload report (first upload for this project)
    with open("reports/smoke_test.json", "rb") as f:
        r = client.post(
            "/api/v1/upload",
            data={"project_name": "first-upload-test", "commit": "xyz789", "branch": "main"},
            files={"file": ("smoke_test.json", f, "application/json")},
        )
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "success"
    
    # Get the project ID by querying the project
    with Session(main.engine) as session:
        project = session.exec(select(Project).where(Project.name == "first-upload-test")).first()
        assert project is not None
        project_id = project.id

    # Check that default status_filter (empty string) shows the 'new' issues
    r = client.get(f"/ui/issues?project_id={project_id}")
    assert r.status_code == 200
    # Should show the V501 issue even though it's status is 'new'
    assert "V501" in r.text
    # Should NOT show the "not found" message
    assert "Предупреждений не найдено" not in r.text

