"""Small helpers exposed to Jinja templates (keep import graph shallow)."""

from __future__ import annotations

SOFTWARE_QUALITY_LABELS: dict[str, str] = {
    "BUG": "Reliability",
    "SECURITY": "Security",
    "VULNERABILITY": "Security",
    "CODE_SMELL": "Maintainability",
    "DEFECT": "Reliability",
}


def software_quality_label(classifier_type: str | None) -> str:
    """PVS classifier type → SonarQube-style software quality label."""
    if not classifier_type:
        return "Maintainability"
    return SOFTWARE_QUALITY_LABELS.get(classifier_type.upper(), "Maintainability")
