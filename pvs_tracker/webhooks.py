"""Webhook module for quality gate failures and CI/CD integration."""

import os
import json
from typing import Optional
from datetime import datetime
from sqlmodel import Session, select
import httpx

from pvs_tracker.models import Run, Project, QualityGate


# ---------------------------------------------------------------------------
# Webhook configuration
# ---------------------------------------------------------------------------

WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")


# ---------------------------------------------------------------------------
# Webhook payload builder
# ---------------------------------------------------------------------------

def build_quality_gate_payload(
    project: Project,
    run: Run,
    quality_gate_result: dict,
) -> dict:
    """Build webhook payload for quality gate evaluation."""
    return {
        "event": "quality_gate_evaluated",
        "timestamp": datetime.utcnow().isoformat(),
        "project": {
            "id": project.id,
            "name": project.name,
        },
        "run": {
            "id": run.id,
            "commit": run.commit,
            "branch": run.branch,
            "timestamp": run.timestamp.isoformat(),
            "status": run.status,
        },
        "quality_gate": quality_gate_result,
        "summary": {
            "total_issues": run.total_issues,
            "new_issues": run.new_issues,
            "fixed_issues": run.fixed_issues,
        },
    }


def build_upload_payload(
    project: Project,
    run: Run,
    issue_count: int,
) -> dict:
    """Build webhook payload for report upload."""
    return {
        "event": "report_uploaded",
        "timestamp": datetime.utcnow().isoformat(),
        "project": {
            "id": project.id,
            "name": project.name,
        },
        "run": {
            "id": run.id,
            "commit": run.commit,
            "branch": run.branch,
            "timestamp": run.timestamp.isoformat(),
            "status": run.status,
        },
        "issue_count": issue_count,
    }


# ---------------------------------------------------------------------------
# Webhook sender
# ---------------------------------------------------------------------------

async def send_webhook(url: str, payload: dict, secret: Optional[str] = None) -> bool:
    """Send webhook payload to URL."""
    if not url:
        return False

    try:
        headers = {"Content-Type": "application/json"}
        
        # Add signature header if secret is provided
        if secret:
            import hmac
            import hashlib
            payload_str = json.dumps(payload)
            signature = hmac.new(
                secret.encode(),
                payload_str.encode(),
                hashlib.sha256
            ).hexdigest()
            headers["X-Webhook-Signature"] = signature

        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, headers=headers, timeout=10.0)
            response.raise_for_status()
            return True
    except Exception as e:
        print(f"Webhook failed: {e}")
        return False


# ---------------------------------------------------------------------------
# Quality gate webhook trigger
# ---------------------------------------------------------------------------

async def trigger_quality_gate_webhook(
    session: Session,
    project_id: int,
    run_id: int,
    quality_gate_result: dict,
) -> bool:
    """Trigger webhook for quality gate evaluation."""
    if not WEBHOOK_URL:
        return False

    project = session.get(Project, project_id)
    run = session.get(Run, run_id)

    if not project or not run:
        return False

    payload = build_quality_gate_payload(project, run, quality_gate_result)
    return await send_webhook(WEBHOOK_URL, payload, WEBHOOK_SECRET)
