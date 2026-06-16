"""Проверка доступности внешних интеграций и состояния сервиса."""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

import requests
from requests_ntlm import HttpNtlmAuth
from sqlmodel import Session, text

from pvs_tracker.ci_config import ci_settings

logger = logging.getLogger(__name__)

APP_VERSION = "0.2.0"
_REQUEST_TIMEOUT = 10


def _integration_result(
    *,
    name: str,
    status: str,
    url: str,
    message: str,
    latency_ms: Optional[int] = None,
    details: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "url": url,
        "message": message,
        "latency_ms": latency_ms,
        "details": details or {},
    }


def check_service_health(session: Session) -> dict[str, Any]:
    """Состояние самого PVS-Tracker (БД и версия)."""
    started = time.monotonic()
    try:
        session.exec(text("SELECT 1")).first()
        latency_ms = int((time.monotonic() - started) * 1000)
        return _integration_result(
            name="service",
            status="ok",
            url="",
            message="PVS-Studio Tracker is running",
            latency_ms=latency_ms,
            details={"version": APP_VERSION, "database": "ok"},
        )
    except Exception as e:
        logger.error("Service health check failed: %s", e)
        return _integration_result(
            name="service",
            status="error",
            url="",
            message=f"Database unavailable: {e}",
            details={"version": APP_VERSION, "database": "error"},
        )


def check_jira_health() -> dict[str, Any]:
    """Проверка подключения к Jira."""
    url = ci_settings.JIRA_URL.rstrip("/")
    if not url or not ci_settings.JIRA_USERNAME:
        return _integration_result(
            name="jira",
            status="not_configured",
            url=url,
            message="JIRA_URL or JIRA_USERNAME is not set",
        )

    started = time.monotonic()
    try:
        from jira import JIRA

        cert: Any = True
        if ci_settings.JIRA_VERIFY_CERT:
            from pathlib import Path

            cert_path = Path(ci_settings.JIRA_VERIFY_CERT)
            if cert_path.is_file():
                cert = str(cert_path)

        client = JIRA(
            options={"server": url, "verify": cert, "check_update": False},
            basic_auth=(ci_settings.JIRA_USERNAME, ci_settings.JIRA_PASSWORD),
            max_retries=0,
            timeout=_REQUEST_TIMEOUT,
        )
        info = client.server_info()
        latency_ms = int((time.monotonic() - started) * 1000)
        version = info.get("version", "unknown") if isinstance(info, dict) else "unknown"
        return _integration_result(
            name="jira",
            status="ok",
            url=url,
            message=f"Connected (Jira {version})",
            latency_ms=latency_ms,
            details={"version": version},
        )
    except Exception as e:
        logger.warning("Jira health check failed: %s", e)
        return _integration_result(
            name="jira",
            status="error",
            url=url,
            message=str(e),
        )


def check_tfs_health() -> dict[str, Any]:
    """Проверка подключения к TFS/Azure DevOps Server."""
    url = ci_settings.TFS_BASE_URL.rstrip("/")
    if not url:
        return _integration_result(
            name="tfs",
            status="not_configured",
            url="",
            message="TFS_BASE_URL is not set",
        )

    started = time.monotonic()
    try:
        response = requests.get(
            f"{url}/_apis/projects",
            auth=HttpNtlmAuth(ci_settings.WEBHOOK_USERNAME, ci_settings.WEBHOOK_PASSWORD),
            params={"api-version": "2.0", "$top": 1},
            timeout=_REQUEST_TIMEOUT,
        )
        latency_ms = int((time.monotonic() - started) * 1000)
        if response.status_code == 200:
            count = response.json().get("count")
            return _integration_result(
                name="tfs",
                status="ok",
                url=url,
                message="Connected",
                latency_ms=latency_ms,
                details={"projects_visible": count},
            )
        return _integration_result(
            name="tfs",
            status="error",
            url=url,
            message=f"HTTP {response.status_code}",
            latency_ms=latency_ms,
        )
    except Exception as e:
        logger.warning("TFS health check failed: %s", e)
        return _integration_result(
            name="tfs",
            status="error",
            url=url,
            message=str(e),
        )


def check_sonarqube_health() -> dict[str, Any]:
    """Проверка подключения к SonarQube."""
    url = ci_settings.SONARQUBE_URL.rstrip("/")
    if not url:
        return _integration_result(
            name="sonarqube",
            status="not_configured",
            url="",
            message="SONARQUBE_URL is not set",
        )

    started = time.monotonic()
    try:
        session = requests.Session()
        if ci_settings.SONARQUBE_TOKEN:
            session.auth = (ci_settings.SONARQUBE_TOKEN, "")

        response = session.get(
            f"{url}/api/system/status",
            timeout=_REQUEST_TIMEOUT,
        )
        latency_ms = int((time.monotonic() - started) * 1000)
        if response.status_code != 200:
            return _integration_result(
                name="sonarqube",
                status="error",
                url=url,
                message=f"HTTP {response.status_code}",
                latency_ms=latency_ms,
            )

        payload = response.json()
        sq_status = payload.get("status", "UNKNOWN")
        if sq_status == "UP":
            return _integration_result(
                name="sonarqube",
                status="ok",
                url=url,
                message="Connected (status UP)",
                latency_ms=latency_ms,
                details={"sonarqube_status": sq_status},
            )
        return _integration_result(
            name="sonarqube",
            status="error",
            url=url,
            message=f"SonarQube status: {sq_status}",
            latency_ms=latency_ms,
            details={"sonarqube_status": sq_status},
        )
    except Exception as e:
        logger.warning("SonarQube health check failed: %s", e)
        return _integration_result(
            name="sonarqube",
            status="error",
            url=url,
            message=str(e),
        )


def collect_integration_health(session: Session) -> dict[str, Any]:
    """Сводка статусов сервиса и интеграций."""
    checks = [
        check_service_health(session),
        check_jira_health(),
        check_tfs_health(),
        check_sonarqube_health(),
    ]
    return {
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "integrations": checks,
    }
