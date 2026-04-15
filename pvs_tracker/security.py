"""Password hashing and security utilities."""

import bcrypt
from datetime import datetime, timedelta
from typing import Optional


def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    """Verify a password against its hash."""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def generate_token() -> str:
    """Generate a secure random token."""
    import secrets
    return secrets.token_urlsafe(32)


def calculate_technical_debt(severity: str, priority: str, classifier_remediation: int = 5) -> int:
    """Calculate technical debt in minutes based on severity and priority.

    Base remediation from classifier is adjusted by severity multiplier.
    """
    severity_multipliers = {
        "High": 2.0,
        "Medium": 1.0,
        "Low": 0.5,
        "Analysis": 0.25,
    }

    priority_multipliers = {
        "CRITICAL": 3.0,
        "MAJOR": 2.0,
        "MINOR": 1.0,
        "INFO": 0.5,
    }

    severity_mult = severity_multipliers.get(severity, 1.0)
    priority_mult = priority_multipliers.get(priority, 1.0)

    # Calculate: base * severity * priority, minimum 1 minute
    debt = classifier_remediation * severity_mult * priority_mult
    return max(1, int(debt))
