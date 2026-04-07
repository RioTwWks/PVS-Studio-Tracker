import hashlib
import json
from typing import Any


def compute_fingerprint(file: str, line: int, code: str, message: str) -> str:
    """Create a stable fingerprint for an issue based on location and message."""
    norm_msg = " ".join(message.split())
    raw = f"{file.replace(chr(92), '/')}:{line}:{code}:{norm_msg}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def parse_pvs_report(report_path: str) -> list[dict[str, Any]]:
    """Parse a PVS-Studio JSON report and return a list of normalized issues."""
    with open(report_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # PVS-Studio typically returns {"version": "...", "warnings": [...]}
    warnings = data.get("warnings", data if isinstance(data, list) else [])

    issues: list[dict[str, Any]] = []
    for w in warnings:
        fp = compute_fingerprint(
            file=w.get("fileName", w.get("file", "")),
            line=int(w.get("lineNumber", w.get("line", 0))),
            code=w.get("warningCode", w.get("code", "")),
            message=w.get("message", ""),
        )
        issues.append(
            {
                "fingerprint": fp,
                "file_path": w.get("fileName", ""),
                "line": int(w.get("lineNumber", 0)),
                "rule_code": w.get("warningCode", ""),
                "severity": w.get("level", w.get("severity", "Medium")),
                "message": w.get("message", ""),
            }
        )
    return issues
