"""Upload API stores Git commit author fields on Run."""

from pathlib import Path

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from pvs_tracker.db import engine
from pvs_tracker.models import Project, Run


def test_upload_stores_commit_author(client: TestClient) -> None:
    client.post("/login", data={"username": "alice", "password": "secret"}, follow_redirects=False)

    with open("reports/smoke_test.json", "rb") as report_file:
        response = client.post(
            "/api/v1/upload",
            data={
                "project_name": "author-upload-test",
                "commit": "abc1234",
                "branch": "main",
                "commit_author_name": "Ivan Developer",
                "commit_author_email": "ivan@example.com",
            },
            files={"file": ("smoke_test.json", report_file, "application/json")},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["commit"] == "abc1234"
    assert body["commit_author_name"] == "Ivan Developer"
    assert body["commit_author_email"] == "ivan@example.com"

    with Session(engine) as session:
        project = session.exec(
            select(Project).where(Project.name == "author-upload-test")
        ).first()
        assert project is not None
        run = session.exec(select(Run).where(Run.project_id == project.id)).first()
        assert run is not None
        assert run.commit_author_name == "Ivan Developer"
        assert run.commit_author_email == "ivan@example.com"


def test_resolve_commit_metadata_from_git_repo(tmp_path: Path) -> None:
    import subprocess

    from pvs_snapshot import resolve_commit_metadata

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "dev@example.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Dev User"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    sample = tmp_path / "sample.txt"
    sample.write_text("hello", encoding="utf-8")
    subprocess.run(["git", "add", "sample.txt"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    meta = resolve_commit_metadata(tmp_path)
    assert meta["commit_author_name"] == "Dev User"
    assert meta["commit_author_email"] == "dev@example.com"
    assert len(meta["commit"]) == 40


def test_upload_applies_commit_metadata_file(client: TestClient) -> None:
    import json

    client.post("/login", data={"username": "alice", "password": "secret"}, follow_redirects=False)

    meta_bytes = json.dumps(
        {
            "commit": "meta-commit-sha",
            "commit_author_name": "From Meta",
            "commit_author_email": "meta@example.com",
        }
    ).encode("utf-8")

    with open("reports/smoke_test.json", "rb") as report_file:
        response = client.post(
            "/api/v1/upload",
            data={
                "project_name": "meta-file-upload-test",
                "branch": "main",
            },
            files={
                "file": ("smoke_test.json", report_file, "application/json"),
                "commit_metadata": ("snapshot.meta.json", meta_bytes, "application/json"),
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["commit"] == "meta-commit-sha"
    assert body["commit_author_name"] == "From Meta"
    assert body["commit_author_email"] == "meta@example.com"


def test_form_fields_override_metadata_file(client: TestClient) -> None:
    import json

    client.post("/login", data={"username": "alice", "password": "secret"}, follow_redirects=False)

    meta_bytes = json.dumps(
        {
            "commit": "from-meta",
            "commit_author_name": "Meta Name",
            "commit_author_email": "meta@example.com",
        }
    ).encode("utf-8")

    with open("reports/smoke_test.json", "rb") as report_file:
        response = client.post(
            "/api/v1/upload",
            data={
                "project_name": "meta-override-test",
                "branch": "main",
                "commit": "form-commit",
                "commit_author_email": "form@example.com",
            },
            files={
                "file": ("smoke_test.json", report_file, "application/json"),
                "commit_metadata": ("snapshot.meta.json", meta_bytes, "application/json"),
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["commit"] == "form-commit"
    assert body["commit_author_name"] == "Meta Name"
    assert body["commit_author_email"] == "form@example.com"
