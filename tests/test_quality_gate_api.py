"""Tests for quality gate API (admin CRUD)."""

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from pvs_tracker import main
from pvs_tracker.models import Project, QualityGate, User


def _admin_token(client: TestClient) -> str:
    with Session(main.engine) as session:
        admin = session.exec(select(User).where(User.username == "admin")).first()
        if not admin:
            pytest.skip("admin user not seeded")
    r = client.post(
        "/api/v2/auth/login",
        json={"username": "admin", "password": "admin"},
    )
    if r.status_code != 200:
        pytest.skip("admin login failed")
    return r.json()["access_token"]


@pytest.fixture()
def client() -> TestClient:
    return TestClient(main.app)


@pytest.fixture()
def admin_headers(client: TestClient) -> dict[str, str]:
    token = _admin_token(client)
    return {"Authorization": f"Bearer {token}"}


def test_create_update_delete_quality_gate(client: TestClient, admin_headers: dict[str, str]) -> None:
    create = client.post(
        "/api/v2/quality-gates",
        headers=admin_headers,
        json={"name": "API Test Gate", "is_default": False, "rule_codes": ["V501", "V502"]},
    )
    assert create.status_code == 200
    gate_id = create.json()["id"]

    detail = client.get(f"/api/v2/quality-gates/{gate_id}", headers=admin_headers)
    assert detail.status_code == 200
    assert set(detail.json()["rule_codes"]) == {"V501", "V502"}

    updated = client.put(
        f"/api/v2/quality-gates/{gate_id}",
        headers=admin_headers,
        json={"name": "API Test Gate Renamed", "rule_codes": ["V501"]},
    )
    assert updated.status_code == 200
    assert updated.json()["rule_codes"] == ["V501"]

    deleted = client.delete(f"/api/v2/quality-gates/{gate_id}", headers=admin_headers)
    assert deleted.status_code == 200


def test_delete_gate_in_use_returns_409(client: TestClient, admin_headers: dict[str, str]) -> None:
    create = client.post(
        "/api/v2/quality-gates",
        headers=admin_headers,
        json={"name": "In Use Gate", "is_default": False, "rule_codes": ["V501"]},
    )
    gate_id = create.json()["id"]

    with Session(main.engine) as session:
        project = Project(name="qg-api-in-use-project")
        session.add(project)
        session.commit()
        session.refresh(project)
        project.quality_gate_id = gate_id
        session.add(project)
        session.commit()
        project_id = project.id

    deleted = client.delete(f"/api/v2/quality-gates/{gate_id}", headers=admin_headers)
    assert deleted.status_code == 409

    with Session(main.engine) as session:
        p = session.get(Project, project_id)
        if p:
            p.quality_gate_id = None
            session.add(p)
            session.commit()
    client.delete(f"/api/v2/quality-gates/{gate_id}", headers=admin_headers)
