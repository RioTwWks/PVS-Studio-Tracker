"""Jira REST client for PVS issue sync."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from pvs_tracker.ci_config import ci_settings
from pvs_tracker.models import Issue, Run

logger = logging.getLogger(__name__)

_jira_service: Optional["JiraService"] = None


class JiraService:
    def __init__(self) -> None:
        self._client: Any = None

    def _cert_path(self) -> Any:
        if ci_settings.JIRA_VERIFY_CERT:
            p = Path(ci_settings.JIRA_VERIFY_CERT)
            if p.is_file():
                return str(p)
        return True

    @property
    def client(self) -> Any:
        if self._client is None:
            from jira import JIRA

            self._client = JIRA(
                options={
                    "server": ci_settings.JIRA_URL,
                    "verify": self._cert_path(),
                    "check_update": False,
                },
                basic_auth=(ci_settings.JIRA_USERNAME, ci_settings.JIRA_PASSWORD),
                max_retries=1,
            )
            logger.info("Jira client initialized")
        return self._client

    def is_connected(self) -> bool:
        try:
            self.client
            return True
        except Exception as e:
            logger.error("Jira connection failed: %s", e)
            return False

    def get_project_key(self, project_name: str) -> Optional[str]:
        try:
            for project in self.client.projects():
                if project.key == project_name or project.name == project_name:
                    return project.key
        except Exception as e:
            logger.error("Jira project lookup failed: %s", e)
        return None

    def find_issue_by_fingerprint(self, jira_project_key: str, fingerprint: str) -> Optional[str]:
        field = ci_settings.JIRA_FINGERPRINT_FIELD
        jql = f'project = "{jira_project_key}" AND "{field}" ~ "{fingerprint}"'
        try:
            issues = self.client.search_issues(jql, maxResults=1)
            if issues:
                return issues[0].key
        except Exception:
            jql = f'project = "{jira_project_key}" AND labels = "pvs-fp-{fingerprint}"'
            try:
                issues = self.client.search_issues(jql, maxResults=1)
                if issues:
                    return issues[0].key
            except Exception as e:
                logger.warning("Jira search failed: %s", e)
        return None

    def _resolve_assignee(self, *, email: str, name: str) -> Optional[str]:
        email = (email or "").strip()
        name = (name or "").strip()
        queries: list[str] = []
        if email:
            queries.append(email)
        if name:
            queries.append(name)
        if email and "@" in email:
            queries.append(email.split("@", 1)[0])

        for query in queries:
            try:
                users = self.client.search_users(query, maxResults=1)
                if users:
                    user = users[0]
                    jira_name = getattr(user, "name", None)
                    if jira_name:
                        logger.info(
                            "Jira assignee resolved: %s (query=%s)",
                            jira_name,
                            query,
                        )
                        return str(jira_name)
            except Exception as e:
                logger.debug("Jira user search failed for %s: %s", query, e)

        if name:
            return name
        if email and "@" in email:
            return email.split("@", 1)[0]
        return email or None

    def resolve_assignee_from_run(self, run: Run) -> Optional[str]:
        """Resolve Jira assignee from commit author on the run (not project owner)."""
        return self._resolve_assignee(
            email=run.commit_author_email or "",
            name=run.commit_author_name or "",
        )

    def resolve_assignee_from_issue(self, issue: Issue, run: Run) -> Optional[str]:
        """
        Resolve Jira assignee for a specific warning.

        Prefer the issue author (who introduced it), fallback to the run commit author.
        """
        email = (issue.author_email or "").strip() or (run.commit_author_email or "")
        name = (issue.author_name or "").strip() or (run.commit_author_name or "")
        return self._resolve_assignee(email=email, name=name)

    def _assignee_field(self, assignee: str) -> dict[str, str]:
        """Build assignee payload for Jira Server (name) or Cloud (accountId)."""
        if len(assignee) >= 20 and "-" in assignee and "@" not in assignee:
            return {"accountId": assignee}
        return {"name": assignee}

    def create_bug(
        self,
        jira_project_key: str,
        summary: str,
        description: str,
        fingerprint: str,
        assignee: Optional[str] = None,
        version: Optional[str] = None,
    ) -> Optional[str]:
        custom_fields: dict[str, Any] = {}
        if ci_settings.JIRA_FINGERPRINT_FIELD:
            custom_fields[ci_settings.JIRA_FINGERPRINT_FIELD] = fingerprint
        issue_fields: dict[str, Any] = {
            "project": {"key": jira_project_key},
            "summary": summary[:255],
            "description": description,
            "issuetype": {"name": "Bug"},
            "labels": [f"pvs-fp-{fingerprint}"],
        }
        if assignee:
            issue_fields["assignee"] = self._assignee_field(assignee)
        issue_fields.update(custom_fields)
        try:
            issue = self.client.create_issue(fields=issue_fields)
            logger.info("Created Jira issue %s", issue.key)
            return str(issue.key)
        except Exception as e:
            logger.error("Jira create failed: %s", e, exc_info=True)
            return None

    def add_comment(self, issue_key: str, comment: str) -> bool:
        try:
            issue = self.client.issue(issue_key)
            self.client.add_comment(issue, comment)
            return True
        except Exception as e:
            logger.error("Jira comment failed: %s", e)
            return False


def get_jira_service() -> JiraService:
    global _jira_service
    if _jira_service is None:
        _jira_service = JiraService()
    return _jira_service
