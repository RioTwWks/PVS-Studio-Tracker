"""
Integration tests for webhook flows.

Tests full end-to-end scenarios:
- Git push → Jenkins trigger
- TFVC check-in → Jenkins trigger
- SonarQube webhook → Jira issue creation
"""

import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app import crud
from app.database import Base, get_db


# Test Fixtures

TEST_DATABASE_URL = "sqlite:///./test_integration.db"


@pytest.fixture(scope="module")
# Create test database engine
def test_engine():
    engine = create_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
# Create test database session
def test_db(test_engine):
    TestingSessionLocal = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=test_engine
    )
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(scope="function")
# Create test client with overridden database dependency
def client(test_db):
    def override_get_db():
        try:
            yield test_db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.fixture
# Create test project in database
def test_project(test_db):
    project_data = {
        "group_id": 1,
        "author_email": "test@example.com",
        "sonar_project_name": "TestProject",
        "sonar_project_key": "test_project_key",
        "jira_project": "TEST",
        "cvs_system": "Git",
        "tfs_path": "http://repo.git",
        "sub_modules": False,
        "another_branch": "master",
        "life_time": "2025-12",
        "cmake_msbuild": "CMake",
        "select_vcxproj": "",
        "pvs_exclude_vcxproj": "",
        "pvs_exclude_path": "",
        "pvs_check_conf_name": "Release",
        "pvs_check_arch": "x64",
        "cmake_win_commands": "",
        "cmake_linux_commands": "",
        "disabled": False,
        "last_processed_changeset": "",
        "version": "1.0.0",
        "disable_jira": True,
    }
    project = crud.create_project(test_db, project_data)
    yield project
    crud.delete_project(test_db, project.id)


# Git Webhook Integration Tests

# Integration tests for Git webhook flow
class TestGitWebhookIntegration:

    @patch('app.webhooks.settings')
    # Test that Git push webhook triggers Jenkins job
    def test_git_push_triggers_jenkins(
        self,
        mock_settings,
        client,
        test_db,
        test_project
    ):
        # Mock authentication settings
        mock_settings.WEBHOOK_USERNAME = "test"
        mock_settings.WEBHOOK_PASSWORD = "test"

        payload = {
            "eventType": "git.push",
            "resource": {
                "commits": [{
                    "commitId": "abc123",
                    "author": {"name": "Test User"},
                    "comment": "Test commit"
                }],
                "refUpdates": [{
                    "name": "refs/heads/master",
                    "oldObjectId": "0000000000000000000000000000000000000000",
                    "newObjectId": "abc123"
                }],
                "repository": {"name": "TestProject"}
            }
        }

        headers = {
            "Content-Type": "application/json",
            "X-TFS-Repo-Type": "Git",
            "X-TFS-Repo-Name": "TestProject/master",
            "X-TFS-Proj-Name": "TestProject",
            "X-TFS-Group-Name": "TestGroup",
            "Authorization": "Basic dGVzdDp0ZXN0"  # test:test
        }

        with patch('app.webhooks.trigger_jenkins_build') as mock_jenkins:
            mock_jenkins.return_value = 12345

            response = client.post("/webhook", json=payload, headers=headers)

            assert response.status_code == 200
            mock_jenkins.assert_called()

    @patch('app.webhooks.settings')
    # Test Git push with no C/C++ changes
    def test_git_push_no_changes(
        self,
        mock_settings,
        client,
        test_db,
        test_project
    ):
        # Mock authentication settings
        mock_settings.WEBHOOK_USERNAME = "test"
        mock_settings.WEBHOOK_PASSWORD = "test"

        payload = {
            "eventType": "git.push",
            "resource": {
                "commits": [{
                    "commitId": "abc123",
                    "changes": [{
                        "item": {"path": "README.md"}
                    }]
                }],
                "refUpdates": [{
                    "name": "refs/heads/master",
                    "newObjectId": "abc123"
                }],
                "repository": {"name": "TestProject"}
            }
        }

        headers = {
            "X-TFS-Repo-Type": "Git",
            "X-TFS-Repo-Name": "TestProject/master",
            "X-TFS-Proj-Name": "TestProject",
            "Authorization": "Basic dGVzdDp0ZXN0"
        }

        with patch('app.services.repository_service.check_git_changes') as mock_check:
            mock_check.return_value = ([], "NO", False, False)

            response = client.post("/webhook", json=payload, headers=headers)

            assert response.status_code == 200


# SonarQube Webhook Integration Tests

# Integration tests for SonarQube webhook flow
class TestSonarQubeWebhookIntegration:

    @patch('app.sonarqube_webhook.process_sonarqube_webhook')
    # Test SonarQube webhook processes issues
    def test_sonarqube_webhook_processes_issues(
        self,
        mock_process,
        client,
        test_db,
        test_project
    ):
        payload = {
            "serverUrl": "http://sonarqube",
            "taskId": "AXYZ123",
            "status": "SUCCESS",
            "analysedAt": "2025-01-01T00:00:00Z",
            "project": {
                "key": "test_project_key",
                "name": "TestProject"
            },
            "branch": {
                "name": "master",
                "type": "BRANCH",
                "isMain": True
            },
            "qualityGate": {
                "name": "Default",
                "status": "OK",
                "conditions": []
            }
        }

        response = client.post(
            "/sonarqube-webhook",
            json=payload,
            headers={"Content-Type": "application/json"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "accepted"

    # Test SonarQube webhook with invalid payload
    def test_sonarqube_webhook_invalid_payload(
        self,
        client,
        test_db
    ):
        payload = {"invalid": "data"}

        response = client.post(
            "/sonarqube-webhook",
            json=payload,
            headers={"Content-Type": "application/json"}
        )

        # Should return 400 for invalid payload
        assert response.status_code == 400


# Health Check Integration Tests

# Integration tests for health check endpoints
class TestHealthCheckIntegration:

    # Test webhook health endpoint
    def test_webhook_health_check(self, client):
        response = client.get("/webhook/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "service" in data

    # Test SonarQube webhook health endpoint
    def test_sonarqube_health_check(self, client):
        response = client.get("/sonarqube-webhook/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "sonarqube-webhook"

    # Test main health endpoint
    def test_main_health_check(self, client):
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"


# Project Management Integration Tests

# Integration tests for project management
class TestProjectManagementIntegration:

    # Test project creation flow
    def test_create_project_flow(self, client, test_db):
        project_data = {
            "group_id": "1",
            "author_email": "test@example.com",
            "sonar_project_name": "NewProject",
            "sonar_project_key": "new_project_key",
            "jira_project": "NEW",
            "cvs_system": "Git",
            "tfs_path": "http://repo.git",
            "another_branch": "master",
            "pvs_check_conf_name": "Release",
            "pvs_check_arch": "x64",
        }

        with patch('app.sonarqube_api_client.SonarQubeAPIClient.create_sq_project') as mock_sonar:
            mock_sonar.return_value = (True, {})

            response = client.post(
                "/project",
                data=project_data,
                follow_redirects=False
            )

            # Should redirect to /list
            assert response.status_code == 303

            # Verify project was created
            projects = crud.get_projects(test_db)
            assert len(projects) >= 1

    # Test project list endpoint
    def test_list_projects(self, client, test_db, test_project):
        response = client.get("/list")

        assert response.status_code == 200
