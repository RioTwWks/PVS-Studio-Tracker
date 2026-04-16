import hashlib
import json
from typing import Any


# Mapping from PVS-Studio numeric levels to human-readable severity
LEVEL_TO_SEVERITY = {
    0: "Analysis",  # Warnings about analysis process issues
    1: "High",      # Most important warnings
    2: "Medium",    # Medium importance
    3: "Low",       # Low importance / code style
}


def compute_fingerprint(file: str, line: int, code: str, message: str) -> str:
    """Create a stable fingerprint for an issue based on location and message."""
    norm_msg = " ".join(message.split())
    raw = f"{file.replace(chr(92), '/')}:{line}:{code}:{norm_msg}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _extract_severity(warning: dict[str, Any]) -> str:
    """Extract severity from warning, handling both numeric level and string severity."""
    if "level" in warning:
        level = warning["level"]
        # Handle numeric levels (modern format)
        if isinstance(level, int):
            return LEVEL_TO_SEVERITY.get(level, "Medium")
        # Handle string levels (legacy format)
        # Normalize common string values
        level_str = str(level).strip().lower()
        if level_str in ("high", "1"):
            return "High"
        elif level_str in ("medium", "2"):
            return "Medium"
        elif level_str in ("low", "3"):
            return "Low"
        elif level_str in ("analysis", "0"):
            return "Analysis"
    return warning.get("severity", "Medium")


def _extract_positions(warning: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract positions array from warning, handling different formats."""
    positions = warning.get("positions", [])
    if not isinstance(positions, list):
        return []
    return positions


def _extract_cwe(warning: dict[str, Any]) -> int | None:
    """Extract CWE ID from warning if present."""
    cwe = warning.get("cwe")
    if cwe is not None:
        try:
            # CWE IDs can be strings or integers
            return int(cwe)
        except (ValueError, TypeError):
            pass
    return None


def safe_to_int(value) -> int | None:
    """
    Safely convert a value to int.
    Handles: None, str (with strip), float, invalid strings.
    Returns None if conversion is not possible.
    """
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        try:
            return int(value)
        except ValueError:
            # Попробуем как float (на случай "15.0")
            try:
                return int(float(value))
            except ValueError:
                return None
    if isinstance(value, float):
        return int(value)
    return None


def _extract_column_info(warning: dict[str, Any], pos: dict[str, Any] | None = None) -> dict[str, int | None]:
    """Extract column information from warning or position."""
    column = None
    end_line = None
    end_column = None

    # Check position-level columns first
    if pos:
        column = pos.get("column")
        end_line = pos.get("endLine")
        end_column = pos.get("endColumn")

    # Fallback to warning-level columns
    if column is None:
        column = warning.get("column")
    if end_line is None:
        end_line = warning.get("endLine")
    if end_column is None:
        end_column = warning.get("endColumn")

    # ✅ Используем безопасную конвертацию
    return {
        "column": safe_to_int(column),
        "end_line": safe_to_int(end_line),
        "end_column": safe_to_int(end_column),
    }


def parse_pvs_report(report_path: str) -> list[dict[str, Any]]:
    """Parse a PVS-Studio JSON report and return a list of normalized issues.

    Handles both formats:
    - Legacy: fileName, lineNumber, warningCode
    - Modern: positions[].file, positions[].line, code, level (numeric)

    Each issue dict includes:
    - fingerprint, file_path, line, rule_code, severity, message
    - column, end_line, end_column (if present)
    - cwe_id (if present)
    """
    with open(report_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # PVS-Studio typically returns {"version": "...", "warnings": [...]}
    warnings = data.get("warnings", data if isinstance(data, list) else [])

    # Extract CWE from warning-level (applies to all positions)
    issues: list[dict[str, Any]] = []
    for w in warnings:
        # Extract basic fields with fallbacks for different formats
        code = w.get("code", w.get("warningCode", ""))
        message = w.get("message", "")
        severity = _extract_severity(w)
        cwe_id = _extract_cwe(w)

        # Handle positions array (modern format)
        positions = _extract_positions(w)

        if positions:
            # Modern format: one warning can have multiple positions
            for pos in positions:
                file_path = pos.get("file", "")
                line = int(pos.get("line", 0))

                # Use synthetic path for warnings without file location
                if not file_path:
                    file_path = f"__analysis__/{code}"
                    line = 0

                # Extract column info from position
                col_info = _extract_column_info(w, pos)

                fp = compute_fingerprint(
                    file=file_path,
                    line=line,
                    code=code,
                    message=message,
                )
                issue_dict = {
                    "fingerprint": fp,
                    "file_path": file_path,
                    "line": line,
                    "rule_code": code,
                    "severity": severity,
                    "message": message,
                    "cwe_id": cwe_id,
                    **col_info,
                }
                issues.append(issue_dict)
        else:
            # Legacy format or fallback: direct fileName/lineNumber fields
            file_path = w.get("fileName", w.get("file", ""))
            line = int(w.get("lineNumber", w.get("line", 0)))

            # Extract column info from warning level
            col_info = _extract_column_info(w)

            fp = compute_fingerprint(
                file=file_path,
                line=line,
                code=code,
                message=message,
            )
            issue_dict = {
                "fingerprint": fp,
                "file_path": file_path,
                "line": line,
                "rule_code": code,
                "severity": severity,
                "message": message,
                "cwe_id": cwe_id,
                **col_info,
            }
            issues.append(issue_dict)
    return issues
