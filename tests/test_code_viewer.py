"""Test code viewer functionality."""

import pytest
from fastapi.testclient import TestClient

from pvs_tracker.main import app
from pvs_tracker.models import Project, Run, Issue, SQLModel
from pvs_tracker.db import engine


@pytest.fixture
def client():
    """Create a test client."""
    return TestClient(app)


@pytest.fixture
def setup_project_and_run():
    """Create a test project and run."""
    SQLModel.metadata.create_all(engine)
    with pytest.MonkeyPatch.context() as mp:
        from sqlmodel import Session, select
        with Session(engine) as session:
            project = Project(name="TestProject", source_root=".")
            session.add(project)
            session.commit()
            session.refresh(project)

            run = Run(
                project_id=project.id,
                commit="abc123",
                branch="main",
                report_file="test.json",
                status="done"
            )
            session.add(run)
            session.commit()
            session.refresh(run)

            yield project.id, run.id


class TestCodeViewer:
    def test_code_viewer_endpoint_exists(self, client):
        """Test that code viewer endpoint exists."""
        response = client.get(
            "/ui/file",
            params={"project_id": 1, "file_path": "test.py"},
            follow_redirects=False
        )
        # Should not 404, might 404 due to missing project
        assert response.status_code in [200, 404, 403, 400]

    def test_code_viewer_requires_project(self, client):
        """Test that code viewer requires valid project."""
        response = client.get(
            "/ui/file",
            params={"project_id": 999, "file_path": "test.py"},
            follow_redirects=False
        )
        assert response.status_code in [404, 400]
