"""
Unit tests for service layer.

Tests cover:
- Repository service (Git/TFVC operations)
- Jenkins service
- Jira service
- CRUD validation
"""

import pytest
from unittest.mock import Mock, patch

from app.services.repository_service import (
    is_c_file,
    is_cmake_file,
    check_git_changes,
    check_tfvc_changes,
    check_tfvc_merge,
)

from app.services.jenkins_service import (
    JenkinsService,
    get_jenkins_service,
    trigger_jenkins_build,
)

from app.services.jira_service import (
    JiraService,
    get_jira_service,
)

from app import crud


# Repository Service Tests

# Tests for repository service functions
class TestRepositoryService:

    # Test C/C++/C# file detection
    def test_is_c_file_valid_extensions(self):
        assert is_c_file("main.cpp") is True
        assert is_c_file("utils.h") is True
        assert is_c_file("program.cs") is True
        assert is_c_file("lib.cxx") is True
        assert is_c_file("header.hxx") is True

    # Test non-C file detection
    def test_is_c_file_invalid_extensions(self):
        assert is_c_file("script.py") is False
        assert is_c_file("code.java") is False
        assert is_c_file("app.js") is False
        assert is_c_file("README.md") is False
        assert is_c_file("") is False
        assert is_c_file(None) is False

    # Test CMake file detection
    def test_is_cmake_file_valid(self):
        assert is_cmake_file("CMakeLists.txt") is True
        assert is_cmake_file("CMakePresets.json") is True
        assert is_cmake_file("config.cmake") is True
        assert is_cmake_file("CUserMakePresets.json") is True

    # Test non-CMake file detection
    def test_is_cmake_file_invalid(self):
        assert is_cmake_file("Makefile") is False
        assert is_cmake_file("build.sh") is False
        assert is_cmake_file("main.cpp") is False
        assert is_cmake_file("") is False


# Tests for Git change detection
class TestGitChanges:

    @patch('app.services.repository_service.Repo')
    # Test Git changes detection on first scan
    def test_check_git_changes_first_scan(self, mock_repo_class):
        mock_project = Mock()
        mock_project.tfs_path = "http://repo.git"
        mock_project.another_branch = "master"

        files, first_scan, composition, cmake = check_git_changes(
            mock_project,
            last_processed_commit=None,
            last_server_commit="abc123"
        )

        assert files == ['1']
        assert first_scan == "YES"
        assert composition is True
        assert cmake is True

    @patch('app.services.repository_service.shutil.rmtree')
    @patch('app.services.repository_service.Repo')
    # Test Git changes detection with no changes
    def test_check_git_changes_no_changes(self, mock_repo_class, mock_rmtree):
        mock_repo = Mock()
        mock_repo_class.clone_from.return_value = mock_repo

        mock_commit = Mock()
        mock_repo.commit.return_value = mock_commit
        mock_commit.diff.return_value = []

        mock_project = Mock()
        mock_project.tfs_path = "http://repo.git"
        mock_project.another_branch = "master"

        files, first_scan, composition, cmake = check_git_changes(
            mock_project,
            last_processed_commit="def456",
            last_server_commit="abc123"
        )

        assert files == []
        assert first_scan == "NO"


# Tests for TFVC change detection
class TestTFVCChanges:

    @patch('app.services.repository_service.requests.get')
    # Test TFVC changes detection on first scan
    def test_check_tfvc_changes_first_scan(self, mock_get):
        mock_project = Mock()
        mock_project.tfs_path = "$/TestProject"

        files, first_scan, composition, cmake = check_tfvc_changes(
            mock_project,
            last_processed_changeset=None,
            last_server_changeset="123"
        )

        assert files == ['1']
        assert first_scan == "YES"

    @patch('app.services.repository_service.requests.get')
    # Test TFVC merge detection
    def test_check_tfvc_merge_not_found(self, mock_get):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"value": []}
        mock_get.return_value = mock_response

        result = check_tfvc_merge(123)

        assert result is None


# Jenkins Service Tests

# Tests for Jenkins service
class TestJenkinsService:

    # Test Jenkins service initialization
    def test_jenkins_service_initialization(self):
        service = JenkinsService()

        assert service.jenkins_url is not None
        assert service.job_name is not None
        assert service._jenkins is None     # Lazy initialization

    @patch('app.services.jenkins_service.Jenkins')
    # Test Jenkins connection property
    def test_jenkins_property_creates_connection(self, mock_jenkins_class):
        mock_jenkins = Mock()
        mock_jenkins.version = "2.97"
        mock_jenkins_class.return_value = mock_jenkins

        service = JenkinsService()
        jenkins = service.jenkins

        assert jenkins is not None
        assert service._jenkins is not None

    @patch('app.services.jenkins_service.get_jenkins_service')
    # Test triggering Jenkins build
    def test_trigger_jenkins_build(self, mock_get_service):
        mock_service = Mock()
        mock_service.trigger_build.return_value = 12345
        mock_get_service.return_value = mock_service

        mock_project = Mock()
        mock_project.disabled = False

        result = trigger_jenkins_build(
            project=mock_project,
            commit_id="abc123",
            first_scan=False,
            linux_build=False,
            modified_files=["main.cpp"]
        )

        assert result == 12345
        mock_service.trigger_build.assert_called_once()


# Tests for global Jenkins service instance
class TestJenkinsServiceGlobal:

    # Test that get_jenkins_service returns same instance
    def test_get_jenkins_service_singleton(self):
        service1 = get_jenkins_service()
        service2 = get_jenkins_service()

        # Should be same instance (singleton)
        assert service1 is service2


# Jira Service Tests

# Tests for Jira service
class TestJiraService:

    # Test Jira service initialization
    def test_jira_service_initialization(self):
        service = JiraService()

        assert service._client is None      # Lazy initialization
        assert service._server_url is not None

    # Test connection status
    def test_is_connected_initially_false(self):
        service = JiraService()

        assert service.is_connected() is False

    @patch('app.services.jira_service.JIRA')
    # Test Jira client initialization
    def test_initialize_client_success(self, mock_jira_class):
        mock_jira = Mock()
        mock_jira_class.return_value = mock_jira

        service = JiraService()
        service._initialize_client()

        assert service._client is not None
        assert service.is_connected() is True

    @patch('app.services.jira_service.JIRA')
    # Test Jira client initialization failure
    def test_initialize_client_failure(self, mock_jira_class):
        mock_jira_class.side_effect = Exception("Connection failed")

        service = JiraService()
        service._initialize_client()

        assert service._client is None
        assert service.is_connected() is False

    @patch('app.services.jira_service.JIRA')
    # Test reconnection
    def test_reconnect(self, mock_jira_class):
        mock_jira = Mock()
        mock_jira_class.return_value = mock_jira

        service = JiraService()
        service._initialize_client()

        # Disconnect
        service._client = None

        # Reconnect
        result = service.reconnect()

        assert result is True
        assert service.is_connected() is True


# Tests for global Jira service instance
class TestJiraServiceGlobal:

    # Test that get_jira_service returns same instance
    def test_get_jira_service_singleton(self):
        service1 = get_jira_service()
        service2 = get_jira_service()

        # Should be same instance (singleton)
        assert service1 is service2

    @patch('app.services.jira_service.JIRA')
    # Test get_jira_client wrapper function
    def test_get_jira_client_wrapper(self, mock_jira_class):
        mock_jira = Mock()
        mock_jira_class.return_value = mock_jira

        from app.services.jira_service import get_jira_client

        client = get_jira_client()

        # Should return Jira client
        assert client is not None


# CRUD Validation Tests

# Tests for project data validation
class TestCRUDValidation:

    # Test validation with valid data
    def test_validate_project_data_valid(self, test_db):
        from tests.conftest import TEST_PROJECT_DATA

        is_valid, error = crud.validate_project_data(TEST_PROJECT_DATA)
        assert is_valid is True
        assert error == ""

    # Test validation with missing required fields
    def test_validate_project_data_missing_required(self, test_db):
        invalid_data = {"group_id": 1}  # Missing most required fields

        is_valid, error = crud.validate_project_data(invalid_data)
        assert is_valid is False
        assert "Отсутствуют обязательные поля" in error

    # Test validation with empty strings
    def test_validate_project_data_empty_string(self, test_db):
        invalid_data = {
            "group_id": 1,
            "author_email": "",
            "sonar_project_name": "",
            "sonar_project_key": "",
            "cvs_system": "",
            "tfs_path": "",
            "life_time": "",
            "cmake_msbuild": "",
            "pvs_check_conf_name": "",
            "pvs_check_arch": "",
        }

        is_valid, error = crud.validate_project_data(invalid_data)
        assert is_valid is False
        assert "Отсутствуют обязательные поля" in error

    # Test validation with invalid email
    def test_validate_project_data_invalid_email(self, test_db):
        from tests.conftest import TEST_PROJECT_DATA

        invalid_data = TEST_PROJECT_DATA.copy()
        invalid_data["author_email"] = "invalid-email"

        is_valid, error = crud.validate_project_data(invalid_data)
        assert is_valid is False
        assert "Неверный формат email" in error

    # Test validation with various valid email formats
    def test_validate_project_data_valid_email(self, test_db):
        from tests.conftest import TEST_PROJECT_DATA

        # Test various valid email formats
        valid_emails = [
            "user@example.com",
            "user.name@example.com",
            "user+tag@example.co.uk",
            "user_name@sub.example.com",
        ]

        for email in valid_emails:
            test_data = TEST_PROJECT_DATA.copy()
            test_data["author_email"] = email

            is_valid, error = crud.validate_project_data(test_data)
            assert is_valid is True, f"Email {email} should be valid"

    # Test validation with spaces in project name
    def test_validate_project_data_spaces_in_name(self, test_db):
        from tests.conftest import TEST_PROJECT_DATA

        invalid_data = TEST_PROJECT_DATA.copy()
        invalid_data["sonar_project_name"] = "Project With Spaces"

        is_valid, error = crud.validate_project_data(invalid_data)
        assert is_valid is False
        assert "не должно содержать пробелы" in error

    # Test validation with no spaces in project name
    def test_validate_project_data_no_spaces_in_name(self, test_db):
        from tests.conftest import TEST_PROJECT_DATA

        # Test various valid project names
        valid_names = [
            "ProjectName",
            "Project_Name",
            "Project-Name",
            "Project.Name",
            "Project123",
        ]

        for name in valid_names:
            test_data = TEST_PROJECT_DATA.copy()
            test_data["sonar_project_name"] = name

            is_valid, error = crud.validate_project_data(test_data)
            assert is_valid is True, f"Project name {name} should be valid"

    # Test validation with invalid CVS system
    def test_validate_project_data_invalid_cvs(self, test_db):
        from tests.conftest import TEST_PROJECT_DATA

        invalid_data = TEST_PROJECT_DATA.copy()
        invalid_data["cvs_system"] = "SVN"

        is_valid, error = crud.validate_project_data(invalid_data)
        assert is_valid is False
        assert "Неверная CVS система" in error

    # Test that create_project validates data
    def test_create_project_validation(self, test_db):
        invalid_data = {"group_id": 1}  # Missing required fields

        with pytest.raises(ValueError, match="Отсутствуют обязательные поля"):
            crud.create_project(test_db, invalid_data)

    # Test that update_project validates data
    def test_update_project_validation(self, test_db, test_project):
        invalid_data = {"group_id": 1}  # Missing required fields

        with pytest.raises(ValueError, match="Отсутствуют обязательные поля"):
            crud.update_project(test_db, test_project.id, invalid_data)

    # Test that create_project strips whitespace from strings
    def test_create_project_strips_whitespace(self, test_db):
        from tests.conftest import TEST_PROJECT_DATA

        data_with_spaces = TEST_PROJECT_DATA.copy()
        data_with_spaces["sonar_project_name"] = "  TestProject  "
        data_with_spaces["author_email"] = "  test@example.com  "

        project = crud.create_project(test_db, data_with_spaces)

        assert project.sonar_project_name == "TestProject"
        assert project.author_email == "test@example.com"
