import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, create_engine

from pvs_tracker.main import app
from pvs_tracker.models import SQLModel


@pytest.fixture(scope="session")
def db_engine():
    return create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})


@pytest.fixture
def db_session(db_engine):
    SQLModel.metadata.create_all(db_engine)
    with Session(db_engine) as session:
        yield session
    SQLModel.metadata.drop_all(db_engine)


@pytest.fixture
def client(db_session):
    def override_get_session():
        yield db_session

    app.dependency_overrides[get_session_placeholder()] = override_get_session
    yield TestClient(app)
    app.dependency_overrides.clear()


def get_session_placeholder():
    from pvs_tracker.main import get_session

    return get_session


@pytest.fixture
def pvs_sample_json():
    return {
        "version": "8.10",
        "warnings": [
            {
                "fileName": "src/main.cpp",
                "lineNumber": 42,
                "warningCode": "V501",
                "level": "High",
                "message": "Identical expressions in 'if' condition.",
            }
        ],
    }


@pytest.fixture
def ldap_mock(mocker):
    conn = mocker.patch("ldap3.Connection")
    conn.bind.return_value = True
    return conn
