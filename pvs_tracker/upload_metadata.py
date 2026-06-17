"""Parse CI upload metadata (.meta.json from pvs_snapshot.py)."""

from __future__ import annotations

import json
from typing import Any, Optional

_METADATA_KEYS = (
    "commit",
    "commit_author_name",
    "commit_author_email",
    "release_version",
    "report_type",
)


def parse_commit_metadata_bytes(content: bytes) -> dict[str, str]:
    """Parse upload metadata JSON; raises ValueError on invalid input."""
    try:
        payload = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("Metadata file must be UTF-8 JSON") from exc

    try:
        raw: Any = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid metadata JSON: {exc}") from exc

    if not isinstance(raw, dict):
        raise ValueError("Metadata must be a JSON object")

    result: dict[str, str] = {}
    for key in _METADATA_KEYS:
        value = raw.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            result[key] = text
    return result


def merge_commit_upload_fields(
    *,
    commit: Optional[str],
    commit_author_name: Optional[str],
    commit_author_email: Optional[str],
    release_version: Optional[str] = None,
    report_type: Optional[str] = None,
    metadata: Optional[dict[str, str]],
    optional_form: Any,
) -> dict[str, Optional[str]]:
    """
    Merge form fields with metadata file values.
    Non-empty form fields take precedence over the file.
    """
    form = {
        "commit": optional_form(commit),
        "commit_author_name": optional_form(commit_author_name),
        "commit_author_email": optional_form(commit_author_email),
        "release_version": optional_form(release_version),
        "report_type": optional_form(report_type),
    }
    if not metadata:
        return form

    return {
        "commit": form["commit"] or metadata.get("commit"),
        "commit_author_name": form["commit_author_name"] or metadata.get("commit_author_name"),
        "commit_author_email": form["commit_author_email"] or metadata.get("commit_author_email"),
        "release_version": form["release_version"] or metadata.get("release_version"),
        "report_type": form["report_type"] or metadata.get("report_type"),
    }
