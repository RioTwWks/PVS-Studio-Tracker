from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel, create_engine


class Project(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    language: str = "c++"
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ErrorClassifier(SQLModel, table=True):
    """Reference classifier for PVS-Studio warning codes."""
    id: Optional[int] = Field(default=None, primary_key=True)
    rule_code: str = Field(unique=True, index=True)  # V1001, V1002, etc.
    type: str  # BUG, SECURITY, etc.
    priority: str  # CRITICAL, MAJOR, MINOR, etc.
    name: str  # Short description
    description: str = ""  # Optional detailed description


class Run(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    commit: Optional[str] = None
    branch: Optional[str] = None
    report_file: str
    status: str = "processing"  # processing | done | failed


class Issue(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: int = Field(foreign_key="run.id")
    classifier_id: Optional[int] = Field(default=None, foreign_key="errorclassifier.id")
    fingerprint: str = Field(index=True)  # stable ID for tracking
    file_path: str
    line: int
    rule_code: str
    severity: str  # High, Medium, Low, Analysis
    message: str
    status: str = "existing"  # new | existing | fixed | ignored
