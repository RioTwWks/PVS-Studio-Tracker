"""LDAP authentication tests (mocked ldap3)."""

import pytest
from sqlmodel import Session

from pvs_tracker import main
from pvs_tracker.auth import LdapIdentity, ldap_authenticate
from pvs_tracker.auth_service import authenticate_credentials, provision_ldap_user
from pvs_tracker.models import UserRole


@pytest.fixture
def ldap_enabled(monkeypatch):
    monkeypatch.setenv("LDAP_ENABLED", "true")
    monkeypatch.setenv("LDAP_AUTH_METHOD", "simple")
    monkeypatch.setenv("LDAP_USER_DOMAIN", "company.local")
    monkeypatch.setenv("LDAP_BASE_DN", "")


def test_ldap_authenticate_success(ldap_enabled, ldap_mock):
    ldap_mock.bind.return_value = True

    identity = ldap_authenticate("jdoe", "secret")
    assert identity is not None
    assert identity.username == "jdoe"


def test_ldap_authenticate_failure(ldap_enabled, ldap_mock):
    ldap_mock.bind.return_value = False

    assert ldap_authenticate("jdoe", "bad") is None


def test_ldap_jit_provision_viewer(ldap_enabled, ldap_mock):
    ldap_mock.bind.return_value = True

    with Session(main.engine) as session:
        user = authenticate_credentials(session, "newldap", "pass")
        assert user is not None
        assert user.username == "newldap"
        assert user.role == UserRole.VIEWER
        assert user.auth_provider == "ldap"


def test_ldap_inactive_user_blocked(ldap_enabled, ldap_mock):
    ldap_mock.bind.return_value = True

    identity = LdapIdentity(username="blocked", email="b@example.com")
    with Session(main.engine) as session:
        user = provision_ldap_user(session, identity)
        user.is_active = False
        session.add(user)
        session.commit()

    with Session(main.engine) as session:
        assert authenticate_credentials(session, "blocked", "pass") is None


def test_local_user_not_sent_to_ldap(ldap_enabled, ldap_mock):
    """Existing local account must use bcrypt even when LDAP is enabled."""
    ldap_mock.bind.return_value = True

    with Session(main.engine) as session:
        assert authenticate_credentials(session, "admin", "admin") is not None
    ldap_mock.bind.assert_not_called()


def test_ldap_login_ui(ldap_enabled, ldap_mock, client):
    ldap_mock.bind.return_value = True

    resp = client.post(
        "/login",
        data={"username": "ldapuser", "password": "secret"},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    me = client.get("/api/v2/users/me")
    assert me.status_code == 200
    assert me.json()["username"] == "ldapuser"
    assert me.json()["role"] == "viewer"
