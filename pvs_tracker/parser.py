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


def parse_pvs_report(report_path: str) -> list[dict[str, Any]]:
    """Parse a PVS-Studio JSON report and return a list of normalized issues.
    
    Handles both formats:
    - Legacy: fileName, lineNumber, warningCode
    - Modern: positions[].file, positions[].line, code, level (numeric)
    """
    with open(report_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # PVS-Studio typically returns {"version": "...", "warnings": [...]}
    warnings = data.get("warnings", data if isinstance(data, list) else [])

    issues: list[dict[str, Any]] = []
    for w in warnings:
        # Extract basic fields with fallbacks for different formats
        code = w.get("code", w.get("warningCode", ""))
        message = w.get("message", "")
        severity = _extract_severity(w)
        
        # Handle positions array (modern format)
        positions = _extract_positions(w)
        
        if positions:
            # Modern format: one warning can have multiple positions
            for pos in positions:
                file_path = pos.get("file", "")
                line = int(pos.get("line", 0))
                
                # Skip warnings with empty file paths (analysis-level warnings)
                if not file_path:
                    continue
                    
                fp = compute_fingerprint(
                    file=file_path,
                    line=line,
                    code=code,
                    message=message,
                )
                issues.append(
                    {
                        "fingerprint": fp,
                        "file_path": file_path,
                        "line": line,
                        "rule_code": code,
                        "severity": severity,
                        "message": message,
                    }
                )
        else:
            # Legacy format or fallback: direct fileName/lineNumber fields
            file_path = w.get("fileName", w.get("file", ""))
            line = int(w.get("lineNumber", w.get("line", 0)))
            
            fp = compute_fingerprint(
                file=file_path,
                line=line,
                code=code,
                message=message,
            )
            issues.append(
                {
                    "fingerprint": fp,
                    "file_path": file_path,
                    "line": line,
                    "rule_code": code,
                    "severity": severity,
                    "message": message,
                }
            )
    return issues
