from datetime import datetime
from enum import Enum
from typing import Optional

from sqlmodel import Field, SQLModel, create_engine, Relationship
from sqlalchemy import Text


# ---------------------------------------------------------------------------
# Enums for roles and statuses
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    ADMIN = "admin"
    USER = "user"
    VIEWER = "viewer"


class IssueResolution(str, Enum):
    UNRESOLVED = "unresolved"
    FIXED = "fixed"
    WONTFIX = "wontfix"
    ACKNOWLEDGED = "acknowledged"
    IGNORED = "ignored"


# ---------------------------------------------------------------------------
# Core models
# ---------------------------------------------------------------------------

class Project(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    language: str = "c++"
    description: Optional[str] = Field(default=None)
    
    # Legacy source root configuration (for backward compatibility)
    source_root_win: Optional[str] = Field(
        default=None,
        description="Root directory for source files on Windows server (e.g., C:\\Projects\\src)",
    )
    source_root_linux: Optional[str] = Field(
        default=None,
        description="Root directory for source files on Linux server (e.g., /home/user/src)",
    )
    
    # Git repository configuration (SonarQube-style)
    git_url: Optional[str] = Field(
        default=None,
        description="Git repository URL (e.g., https://github.com/org/repo or git@github.com:org/repo.git)",
    )
    git_branch: Optional[str] = Field(
        default="main",
        description="Default branch to use (main, master, etc.)",
    )
    git_credentials_type: Optional[str] = Field(
        default=None,
        description="Authentication type: 'token', 'ssh_key', 'user_pass', or None for public repos",
    )
    # Note: git_credentials_value should be stored in a secure vault, not in DB
    # This field just indicates the type of auth configured
    
    # Source archive configuration (fallback when Git is not available)
    source_archive_path: Optional[str] = Field(
        default=None,
        description="Path to uploaded source archive (zip/tar) for this project",
    )
    
    quality_gate_id: Optional[int] = Field(default=None, foreign_key="qualitygate.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    runs: list["Run"] = Relationship(back_populates="project")
    members: list["ProjectMember"] = Relationship(back_populates="project")
    quality_gate: Optional["QualityGate"] = Relationship(back_populates="project")


class User(SQLModel, table=True):
    """User model for authentication and authorization."""
    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(unique=True, index=True)
    email: Optional[str] = Field(default=None)
    password_hash: str = Field(description="Hashed password (bcrypt)")
    role: UserRole = Field(default=UserRole.VIEWER)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_login: Optional[datetime] = Field(default=None)

    # Relationships
    comments: list["IssueComment"] = Relationship(back_populates="user")
    project_memberships: list["ProjectMember"] = Relationship(back_populates="user")


class ProjectMember(SQLModel, table=True):
    """Project-level user permissions (overrides global role)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id")
    user_id: int = Field(foreign_key="user.id")
    role: UserRole = Field(default=UserRole.VIEWER)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    project: Project = Relationship(back_populates="members")
    user: User = Relationship(back_populates="project_memberships")


class ErrorClassifier(SQLModel, table=True):
    """Reference classifier for PVS-Studio warning codes."""
    id: Optional[int] = Field(default=None, primary_key=True)
    rule_code: str = Field(unique=True, index=True)  # V1001, V1002, etc.
    type: str  # BUG, SECURITY, etc.
    priority: str  # CRITICAL, MAJOR, MINOR, etc.
    name: str  # Short description
    description: str = ""  # Optional detailed description
    cwe_id: Optional[int] = Field(default=None, description="CWE identifier")
    remediation_effort: int = Field(default=5, description="Estimated minutes to fix")

    # Relationships
    issues: list["Issue"] = Relationship(back_populates="classifier")


class QualityGate(SQLModel, table=True):
    """Configurable quality gate with conditions."""
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    is_default: bool = Field(default=False, description="Default gate for new projects")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    conditions: list["QualityGateCondition"] = Relationship(back_populates="quality_gate")
    project: Optional["Project"] = Relationship(back_populates="quality_gate")


class QualityGateCondition(SQLModel, table=True):
    """Individual condition within a quality gate."""
    id: Optional[int] = Field(default=None, primary_key=True)
    quality_gate_id: int = Field(foreign_key="qualitygate.id")
    metric: str = Field(description="Metric name: new_issues, reliability_rating, etc.")
    operator: str = Field(description="Comparison operator: gt, lt, gte, lte, eq, ne")
    threshold: int = Field(description="Threshold value")
    error_policy: str = Field(default="error", description="error, warn, ignore")

    # Relationships
    quality_gate: QualityGate = Relationship(back_populates="conditions")


class Run(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    commit: Optional[str] = None
    branch: Optional[str] = None
    report_file: str
    status: str = "processing"  # processing | done | failed
    total_issues: int = Field(default=0)
    new_issues: int = Field(default=0)
    fixed_issues: int = Field(default=0)
    analysis_time_ms: int = Field(default=0, description="Analysis duration in ms")

    # Relationships
    project: Project = Relationship(back_populates="runs")
    issues: list["Issue"] = Relationship(back_populates="run")


class Issue(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: int = Field(foreign_key="run.id")
    classifier_id: Optional[int] = Field(default=None, foreign_key="errorclassifier.id")
    fingerprint: str = Field(index=True)  # stable ID for tracking
    file_path: str
    line: int
    column: Optional[int] = Field(default=None, description="Column number")
    end_line: Optional[int] = Field(default=None, description="End line number")
    end_column: Optional[int] = Field(default=None, description="End column number")
    rule_code: str
    severity: str  # High, Medium, Low, Analysis
    message: str
    status: str = "existing"  # new | existing | fixed | ignored
    resolution: IssueResolution = Field(default=IssueResolution.UNRESOLVED)
    cwe_id: Optional[int] = Field(default=None, description="CWE identifier")
    technical_debt_minutes: int = Field(default=0, description="Estimated remediation time")
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    run: Run = Relationship(back_populates="issues")
    classifier: Optional[ErrorClassifier] = Relationship(back_populates="issues")
    comments: list["IssueComment"] = Relationship(back_populates="issue")


class IssueComment(SQLModel, table=True):
    """Comments on issues for team collaboration."""
    __table_args__ = {"extend_existing": True}
    
    id: Optional[int] = Field(default=None, primary_key=True)
    issue_id: int = Field(foreign_key="issue.id", description="References Issue.id")
    user_id: int = Field(foreign_key="user.id")
    comment: str = Field(sa_type=Text)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    edited_at: Optional[datetime] = Field(default=None)

    # Relationships
    user: User = Relationship(back_populates="comments")
    issue: Issue = Relationship(back_populates="comments")


class ActivityLog(SQLModel, table=True):
    """Audit trail for project activities."""
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: Optional[int] = Field(default=None, foreign_key="project.id")
    user_id: Optional[int] = Field(default=None, foreign_key="user.id")
    action: str = Field(description="upload, delete, ignore, comment, settings_change, etc.")
    entity_type: str = Field(description="project, run, issue, quality_gate, etc.")
    entity_id: Optional[int] = Field(default=None)
    details: Optional[str] = Field(default=None, sa_type=Text)
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class MetricSnapshot(SQLModel, table=True):
    """Historical metric values per run."""
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: int = Field(foreign_key="run.id")
    metric_name: str = Field(description="Lines of code, complexity, coverage, etc.")
    metric_value: float = Field()
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class GlobalSettings(SQLModel, table=True):
    """Глобальные настройки приложения (одна запись)."""
    id: Optional[int] = Field(default=1, primary_key=True)  # Всегда 1
    default_source_root_win: Optional[str] = Field(
        default=None,
        description="Глобальный корень исходников для Windows (используется, если не задан в проекте)"
    )
    default_source_root_linux: Optional[str] = Field(
        default=None,
        description="Глобальный корень исходников для Linux (используется, если не задан в проекте)"
    )
    updated_at: datetime = Field(default_factory=datetime.utcnow)
