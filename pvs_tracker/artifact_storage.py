"""Database-backed storage for uploaded reports and code snapshots."""

import gzip
import json
from typing import Any

from sqlmodel import Session, select

from pvs_tracker.models import CodeSnapshotFile, RunReport


def store_run_report(
    session: Session,
    run_id: int,
    filename: str,
    content: bytes,
    content_type: str | None = None,
) -> None:
    """Store the raw report bytes for a run."""
    existing = session.exec(select(RunReport).where(RunReport.run_id == run_id)).first()
    if existing:
        session.delete(existing)
        session.flush()

    session.add(
        RunReport(
            run_id=run_id,
            filename=filename,
            content_type=content_type,
            content=content,
        )
    )


def decode_snapshot_upload(snapshot_bytes: bytes) -> dict[str, str]:
    """Decode an uploaded snapshot, accepting the current .json.gz format."""
    try:
        payload = gzip.decompress(snapshot_bytes).decode("utf-8", errors="replace")
    except OSError:
        payload = snapshot_bytes.decode("utf-8", errors="replace")

    data: Any = json.loads(payload)
    if not isinstance(data, dict):
        raise ValueError("Code snapshot must be a JSON object: {file_path: content}")

    snapshot: dict[str, str] = {}
    for path, content in data.items():
        if not isinstance(path, str):
            continue
        snapshot[path.replace("\\", "/")] = "" if content is None else str(content)
    return snapshot


def store_code_snapshot(session: Session, run_id: int, snapshot_bytes: bytes) -> int:
    """Store a run-specific code snapshot as per-file DB rows."""
    snapshot = decode_snapshot_upload(snapshot_bytes)

    existing = session.exec(
        select(CodeSnapshotFile).where(CodeSnapshotFile.run_id == run_id)
    ).all()
    for row in existing:
        session.delete(row)
    session.flush()

    for file_path, content in snapshot.items():
        session.add(
            CodeSnapshotFile(
                run_id=run_id,
                file_path=file_path,
                content=content,
            )
        )
    return len(snapshot)
