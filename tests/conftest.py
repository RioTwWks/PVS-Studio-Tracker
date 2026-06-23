import json
import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

_TEST_DB_FILE = tempfile.NamedTemporaryFile(prefix="pvs_tracker_test_", suffix=".db", delete=False)
_TEST_DB_PATH = Path(_TEST_DB_FILE.name)
_TEST_DB_FILE.close()

# This must be set before importing pvs_tracker.main, because db.engine is
# created at import time. Never mutate engine.url after the engine exists.
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB_PATH.as_posix()}"

from pvs_tracker import main  # noqa: E402
from pvs_tracker.models import ErrorClassifier, SQLModel, User, UserRole  # noqa: E402
from pvs_tracker.security import hash_password  # noqa: E402

_FIXTURES_DIR = Path(__file__).parent / "fixtures"
_CLASSIFIERS_CSV = _FIXTURES_DIR / "classifiers.csv"

_SAMPLE_REPORT = {
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

_TEST_USERS: list[tuple[str, str, UserRole]] = [
    ("alice", "secret", UserRole.USER),
    ("bob", "secret", UserRole.VIEWER),
    ("test", "test", UserRole.USER),
]


def _load_test_classifiers(session: Session) -> None:
    """Load a minimal classifier set for tests (replaces removed Actual_warnings.csv)."""
    existing = session.exec(select(ErrorClassifier).limit(1)).first()
    if existing:
        return

    from pvs_tracker.classifier_parser import parse_classifier_csv
    from pvs_tracker.warnings_catalog import backfill_classifier_languages, resolve_warning_language

    classifiers = parse_classifier_csv(str(_CLASSIFIERS_CSV))
    for clf in classifiers:
        clf["language"] = resolve_warning_language(
            clf["rule_code"],
            clf.get("category"),
            clf.get("language"),
        )
        session.add(ErrorClassifier(**clf))
    session.commit()
    backfill_classifier_languages(session)


def _seed_test_users(session: Session) -> None:
    """Create local users expected by integration tests."""
    for username, password, role in _TEST_USERS:
        existing = session.exec(select(User).where(User.username == username)).first()
        if existing:
            continue
        session.add(
            User(
                username=username,
                email=f"{username}@example.com",
                password_hash=hash_password(password),
                auth_provider="local",
                role=role,
                is_active=True,
            )
        )
    session.commit()


@pytest.fixture(autouse=True)
def _disable_ldap_by_default(request, monkeypatch):
    """Prevent accidental LDAP bind during tests unless ldap_enabled fixture is used."""
    if "ldap_enabled" not in request.fixturenames:
        monkeypatch.setenv("LDAP_ENABLED", "false")


@pytest.fixture(autouse=True)
def isolated_db():
    import pvs_tracker.startup_state as startup_state
    from pvs_tracker.startup_state import mark_startup_finished

    startup_state._init_done.clear()
    startup_state._init_error = None

    SQLModel.metadata.drop_all(main.engine)
    main._run_startup_init()
    mark_startup_finished(None)

    with Session(main.engine) as session:
        _load_test_classifiers(session)
        _seed_test_users(session)

    yield

    SQLModel.metadata.drop_all(main.engine)


@pytest.fixture(autouse=True)
def smoke_report_file():
    """Create reports/smoke_test.json used by upload integration tests."""
    reports_dir = Path("reports")
    reports_dir.mkdir(exist_ok=True)
    report_path = reports_dir / "smoke_test.json"
    report_path.write_text(json.dumps(_SAMPLE_REPORT), encoding="utf-8")
    yield report_path


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
def ldap_mock():
    from unittest.mock import MagicMock, patch

    mock_conn = MagicMock()
    mock_conn.bind.return_value = True
    mock_conn.entries = []
    with patch("pvs_tracker.auth.Connection", return_value=mock_conn):
        yield mock_conn
