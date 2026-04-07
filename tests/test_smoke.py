"""Smoke tests for the MVP."""
import json
import os
import tempfile

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from pvs_tracker import main
from pvs_tracker.models import Project, SQLModel

SAMPLE_REPORT = {
    "version": "8.10",
    "warnings": [
        {
            "fileName": "src/main.cpp",
            "lineNumber": 42,
            "warningCode": "V501",
            "level": "High",
            "message": "Identical expressions in 'if' condition.",
        },
    ],
}


@pytest.fixture(autouse=True)
def setup_db():
    """Recreate tables on the app's engine before each test."""
    # Use a temp file for the DB
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    main.engine.url = f"sqlite:///{tmp.name}"
    SQLModel.metadata.drop_all(main.engine)
    SQLModel.metadata.create_all(main.engine)
    yield
    os.unlink(tmp.name)


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
