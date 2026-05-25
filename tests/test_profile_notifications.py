"""Tests for user profile and API upload email notifications."""

from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from pvs_tracker import main
from pvs_tracker.models import Project, ProjectMember, Run, User, UserProjectNotification, UserRole
from pvs_tracker.notifications import _notify_api_upload_subscribers_sync
from pvs_tracker.security import hash_password


def _login_admin(client: TestClient) -> None:
    client.post("/login", data={"username": "admin", "password": "admin"}, follow_redirects=False)


def _jwt_for_user(client: TestClient, username: str, password: str) -> str:
    resp = client.post(
        "/api/v2/auth/login",
        json={"username": username, "password": password},
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


def test_patch_users_me_updates_profile(client: TestClient) -> None:
    _login_admin(client)
    resp = client.patch(
        "/api/v2/users/me",
        json={
            "first_name": "Ivan",
            "last_name": "Petrov",
            "email": "ivan@example.com",
            "notify_api_uploads": True,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["first_name"] == "Ivan"
    assert data["last_name"] == "Petrov"
    assert data["email"] == "ivan@example.com"
    assert data["notify_api_uploads"] is True


def test_put_notifications_rejects_inaccessible_project(client: TestClient) -> None:
    with Session(main.engine) as session:
        project = Project(name="restricted-proj", language="c++")
        session.add(project)
        session.commit()
        session.refresh(project)

        viewer = User(
            username="viewer1",
            email="viewer1@example.com",
            password_hash=hash_password("viewer1"),
            role=UserRole.VIEWER,
            is_active=True,
        )
        session.add(viewer)
        session.commit()
        session.refresh(viewer)

        admin = session.exec(select(User).where(User.username == "admin")).first()
        assert admin is not None
        session.add(
            ProjectMember(project_id=project.id, user_id=admin.id, role=UserRole.ADMIN)
        )
        session.commit()

        project_id = project.id

    token = _jwt_for_user(client, "viewer1", "viewer1")
    resp = client.put(
        "/api/v2/users/me/notifications",
        headers={"Authorization": f"Bearer {token}"},
        json={"project_ids": [project_id]},
    )
    assert resp.status_code == 403


def test_put_notifications_saves_subscriptions(client: TestClient) -> None:
    _login_admin(client)
    with Session(main.engine) as session:
        project = Project(name="notify-proj", language="c++")
        session.add(project)
        session.commit()
        session.refresh(project)
        project_id = project.id

    resp = client.put(
        "/api/v2/users/me/notifications",
        json={"project_ids": [project_id]},
    )
    assert resp.status_code == 200
    assert project_id in resp.json()["project_ids"]

    with Session(main.engine) as session:
        admin = session.exec(select(User).where(User.username == "admin")).first()
        assert admin is not None
        rows = session.exec(
            select(UserProjectNotification).where(UserProjectNotification.user_id == admin.id)
        ).all()
        assert any(r.project_id == project_id for r in rows)


@patch("pvs_tracker.notifications.send_email", return_value=True)
def test_notify_api_upload_subscribers_sends_email(
    mock_send_email: MagicMock,
) -> None:
    with Session(main.engine) as session:
        project = Project(name="email-proj", language="c++")
        session.add(project)
        session.commit()
        session.refresh(project)

        admin = session.exec(select(User).where(User.username == "admin")).first()
        assert admin is not None
        admin.first_name = "Admin"
        admin.email = "admin-notify@example.com"
        admin.notify_api_uploads = True
        session.add(admin)

        run = Run(
            project_id=project.id,
            report_file="db:test.json",
            status="done",
            total_issues=1,
            new_issues=1,
            fixed_issues=0,
        )
        session.add(run)
        session.commit()
        session.refresh(run)

        session.add(
            UserProjectNotification(user_id=admin.id, project_id=project.id)
        )
        session.commit()

        project_id = project.id
        run_id = run.id

    _notify_api_upload_subscribers_sync(
        project_id,
        run_id,
        {"status": "ok", "passed": True},
    )
    mock_send_email.assert_called_once()
    assert mock_send_email.call_args[0][0] == "admin-notify@example.com"


def test_profile_settings_page_requires_auth(client: TestClient) -> None:
    resp = client.get("/ui/settings/profile", follow_redirects=False)
    assert resp.status_code == 401
