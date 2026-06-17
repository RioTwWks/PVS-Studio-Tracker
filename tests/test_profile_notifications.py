"""Tests for user profile and API upload email notifications."""

from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from pvs_tracker import main
from pvs_tracker.models import Project, ProjectMember, Run, User, UserProjectNotification, UserRole
from pvs_tracker.notifications import (
    _notify_api_upload_subscribers_sync,
    subscribe_commit_author_notifications,
)
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


def test_subscribe_commit_author_creates_notification() -> None:
    with Session(main.engine) as session:
        project = Project(name="auto-sub-proj", language="c++")
        session.add(project)
        session.commit()
        session.refresh(project)

        developer = User(
            username="dev1",
            email="dev1@example.com",
            password_hash=hash_password("dev1"),
            role=UserRole.VIEWER,
            is_active=True,
        )
        session.add(developer)
        session.commit()
        session.refresh(developer)

        subscribed = subscribe_commit_author_notifications(
            session, project.id, "dev1@example.com"
        )
        session.commit()

        assert subscribed is True
        developer = session.get(User, developer.id)
        assert developer is not None
        assert developer.notify_api_uploads is True
        rows = session.exec(
            select(UserProjectNotification).where(
                UserProjectNotification.user_id == developer.id,
                UserProjectNotification.project_id == project.id,
            )
        ).all()
        assert len(rows) == 1


def test_subscribe_commit_author_skips_unknown_email() -> None:
    with Session(main.engine) as session:
        project = Project(name="unknown-author-proj", language="c++")
        session.add(project)
        session.commit()
        session.refresh(project)

        subscribed = subscribe_commit_author_notifications(
            session, project.id, "nobody@example.com"
        )
        assert subscribed is False


def test_subscribe_commit_author_skips_restricted_project() -> None:
    with Session(main.engine) as session:
        project = Project(name="restricted-sub-proj", language="c++")
        session.add(project)
        session.commit()
        session.refresh(project)

        admin = session.exec(select(User).where(User.username == "admin")).first()
        assert admin is not None

        outsider = User(
            username="outsider",
            email="outsider@example.com",
            password_hash=hash_password("outsider"),
            role=UserRole.VIEWER,
            is_active=True,
        )
        session.add(outsider)
        session.commit()
        session.refresh(outsider)

        session.add(
            ProjectMember(project_id=project.id, user_id=admin.id, role=UserRole.ADMIN)
        )
        session.commit()

        subscribed = subscribe_commit_author_notifications(
            session, project.id, "outsider@example.com"
        )
        assert subscribed is False


@patch("pvs_tracker.rest_queue.client.enqueue_smtp_api_upload_notify")
def test_api_upload_auto_subscribes_commit_author(
    mock_enqueue_smtp: MagicMock,
    client: TestClient,
    pvs_sample_json: dict,
) -> None:
    import json
    import os

    os.makedirs("reports", exist_ok=True)
    with open("reports/smoke_test.json", "w", encoding="utf-8") as f:
        json.dump(pvs_sample_json, f)

    client.post("/login", data={"username": "admin", "password": "admin"}, follow_redirects=False)

    with Session(main.engine) as session:
        developer = User(
            username="ci-dev",
            email="ci-dev@example.com",
            password_hash=hash_password("ci-dev"),
            role=UserRole.VIEWER,
            is_active=True,
        )
        session.add(developer)
        session.commit()

    with open("reports/smoke_test.json", "rb") as report_file:
        response = client.post(
            "/api/v1/upload",
            data={
                "project_name": "ci-auto-subscribe-test",
                "branch": "main",
                "commit_author_name": "CI Dev",
                "commit_author_email": "ci-dev@example.com",
            },
            files={"file": ("smoke_test.json", report_file, "application/json")},
        )

    assert response.status_code == 200

    with Session(main.engine) as session:
        project = session.exec(
            select(Project).where(Project.name == "ci-auto-subscribe-test")
        ).first()
        assert project is not None
        developer = session.exec(
            select(User).where(User.email == "ci-dev@example.com")
        ).first()
        assert developer is not None
        assert developer.notify_api_uploads is True
        row = session.exec(
            select(UserProjectNotification).where(
                UserProjectNotification.user_id == developer.id,
                UserProjectNotification.project_id == project.id,
            )
        ).first()
        assert row is not None

    mock_enqueue_smtp.assert_called_once()


def test_profile_settings_page_requires_auth(client: TestClient) -> None:
    resp = client.get("/ui/settings/profile", follow_redirects=False)
    assert resp.status_code == 401
