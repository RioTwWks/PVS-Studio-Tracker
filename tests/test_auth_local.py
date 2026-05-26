"""Local authentication tests."""

from sqlmodel import Session

from pvs_tracker import main
from pvs_tracker.auth_service import authenticate_credentials
from pvs_tracker.models import UserRole


def test_bootstrap_admin_login(client):
    resp = client.post(
        "/login",
        data={"username": "admin", "password": "admin"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"

    me = client.get("/api/v2/users/me")
    assert me.status_code == 200
    data = me.json()
    assert data["username"] == "admin"
    assert data["role"] == "admin"


def test_invalid_login(client):
    resp = client.post("/login", data={"username": "admin", "password": "wrong"})
    assert resp.status_code == 200
    assert "Invalid" in resp.text


def test_api_login_sets_session(client):
    resp = client.post(
        "/api/v2/auth/login",
        json={"username": "admin", "password": "admin"},
    )
    assert resp.status_code == 200
    assert "access_token" in resp.json()

    me = client.get("/api/v2/users/me")
    assert me.status_code == 200


def test_authenticate_credentials_local_only(monkeypatch):
    monkeypatch.setenv("LDAP_ENABLED", "false")
    with Session(main.engine) as session:
        user = authenticate_credentials(session, "admin", "admin")
        assert user is not None
        assert user.auth_provider == "local"
        assert user.role == UserRole.ADMIN
