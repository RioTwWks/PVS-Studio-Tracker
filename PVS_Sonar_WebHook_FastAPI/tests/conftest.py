# Встроенные фикстуры для pytest
# Мокинг внешних API
# Тестовые данные

import os
import sys
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Добавление project root в path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.main import app
from app import crud
from app.database import Base, get_db


# Конфигурация

# Тест URL БД (in-memory SQLite)
TEST_DATABASE_URL = "sqlite:///./test_pvs_sonar.db"

# Тест credentials
TEST_WEBHOOK_USERNAME = "test"
TEST_WEBHOOK_PASSWORD = "test"

# Тест данных проекта
TEST_PROJECT_DATA = {
    "group_id": 1,
    "author_email": "test@example.com",
    "sonar_project_name": "TestProject",
    "sonar_project_key": "test_project_key",
    "jira_project": "TEST",
    "cvs_system": "Git",
    "tfs_path": "$/TestProject",
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


# Фикстуры

@pytest.fixture(scope="function")
# Создание тестового компонента database engine
def test_engine():
    engine = create_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
# Создание сеанса тестирования БД
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
# Создание тестового клиента с переопределенной зависимостью от базы данных
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
# Создание тестового проекта в БД
def test_project(test_db):
    project = crud.create_project(test_db, TEST_PROJECT_DATA)
    yield project
    crud.delete_project(test_db, project.id)


@pytest.fixture
# Имитация переменных среды для тестирования
def mock_env_vars(monkeypatch):
    monkeypatch.setenv("WEBHOOK_USERNAME", TEST_WEBHOOK_USERNAME)
    monkeypatch.setenv("WEBHOOK_PASSWORD", TEST_WEBHOOK_PASSWORD)
    monkeypatch.setenv("SONARQUBE_URL", "http://test-sonarqube")
    monkeypatch.setenv("SONARQUBE_TOKEN", "test_token")
    monkeypatch.setenv("SONARQUBE_WEBHOOK_SECRET", "test_secret")
    monkeypatch.setenv("JENKINS_URL", "http://test-jenkins")
    monkeypatch.setenv("JENKINS_TOKEN", "test_jenkins_token")
    monkeypatch.setenv("JIRA_URL", "http://test-jira")
    monkeypatch.setenv("ADMIN_IPS", "127.0.0.1")
    monkeypatch.setenv("ADMIN_HOSTNAMES", "localhost")


# Вспомогательные функции

# Получение базовых заголовков авторизации
def get_basic_auth_headers(username: str, password: str) -> dict:
    import base64
    credentials = f"{username}:{password}"
    encoded = base64.b64encode(credentials.encode()).decode()
    return {"Authorization": f"Basic {encoded}"}


# Примеры Payloads

# Получить пример Git push payload
def get_git_push_payload():
    return {
        "eventType": "git.push",
        "resource": {
            "commits": [
                {
                    "commitId": "abc123def456",
                    "author": {
                        "name": "Test User",
                        "email": "test@example.com"
                    },
                    "comment": "Test commit",
                    "changes": [
                        {
                            "changeType": "edit",
                            "item": {"path": "/src/main.cpp"}
                        }
                    ]
                }
            ],
            "refUpdates": [
                {
                    "name": "refs/heads/master",
                    "oldObjectId": "0000000000000000000000000000000000000000",
                    "newObjectId": "abc123def456"
                }
            ],
            "repository": {
                "name": "TestProject",
                "url": "http://test-tfs/TestProject/_git/TestProject"
            },
            "pushId": 12345
        }
    }


# Получить пример TFVC check-in payload
def get_tfvc_checkin_payload():
    return {
        "eventType": "tfvc.checkin",
        "resource": {
            "changesetId": 98765,
            "author": {
                "displayName": "Test User"
            },
            "comment": "Test check-in",
            "changes": [
                {
                    "changeType": "edit",
                    "item": {"path": "$/TestProject/src/main.cpp"}
                }
            ]
        }
    }


# Получить пример SonarQube webhook payload.
def get_sonarqube_webhook_payload():
    return {
        "serverUrl": "http://test-sonarqube",
        "taskId": "AXYZ123456789",
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
            "name": "Default Quality Gate",
            "status": "OK",
            "conditions": [
                {
                    "metric": "new_coverage",
                    "operator": "LT",
                    "value": "85.5",
                    "status": "OK",
                    "errorThreshold": "80"
                }
            ]
        }
    }


@pytest.fixture
# Имититация переменных среды для тестирования
def mock_env_vars(monkeypatch):
    monkeypatch.setenv("WEBHOOK_USERNAME", TEST_WEBHOOK_USERNAME)
    monkeypatch.setenv("WEBHOOK_PASSWORD", TEST_WEBHOOK_PASSWORD)
    monkeypatch.setenv("SONARQUBE_URL", "http://test-sonarqube")
    monkeypatch.setenv("SONARQUBE_TOKEN", "test_token")
    monkeypatch.setenv("SONARQUBE_WEBHOOK_SECRET", "test_secret")
    monkeypatch.setenv("JENKINS_URL", "http://test-jenkins")
    monkeypatch.setenv("JENKINS_TOKEN", "test_jenkins_token")
    monkeypatch.setenv("JIRA_URL", "http://test-jira")
    monkeypatch.setenv("ADMIN_IPS", "127.0.0.1")
    monkeypatch.setenv("ADMIN_HOSTNAMES", "localhost")
