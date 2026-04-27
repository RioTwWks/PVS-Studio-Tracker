import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session


_TEST_DB_FILE = tempfile.NamedTemporaryFile(prefix="pvs_tracker_test_", suffix=".db", delete=False)
_TEST_DB_PATH = Path(_TEST_DB_FILE.name)
_TEST_DB_FILE.close()

# This must be set before importing pvs_tracker.main, because db.engine is
# created at import time. Never mutate engine.url after the engine exists.
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB_PATH.as_posix()}"

from pvs_tracker import main  # noqa: E402
from pvs_tracker.models import SQLModel  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_db():
    SQLModel.metadata.drop_all(main.engine)
    SQLModel.metadata.create_all(main.engine)
    main._initialize_default_data()

    with Session(main.engine) as session:
        main._load_error_classifiers(session)

    yield

    SQLModel.metadata.drop_all(main.engine)


@pytest.fixture
def client():
    yield TestClient(main.app)


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_db():
    yield
    try:
        _TEST_DB_PATH.unlink(missing_ok=True)
    except PermissionError:
        pass


@pytest.fixture
def pvs_sample_json():
    return {
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
                            "columns": 0,
                        },
                    }
                ],
                "projects": ["demo"],
                "message": "Identical expressions in 'if' condition.",
                "favorite": False,
                "falseAlarm": False,
            }
        ],
    }


@pytest.fixture
def ldap_mock(mocker):
    conn = mocker.patch("ldap3.Connection")
    conn.bind.return_value = True
    return conn
