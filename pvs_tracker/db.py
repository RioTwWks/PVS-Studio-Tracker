"""Database engine and session management."""

import os

from sqlmodel import Session, create_engine

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./pvs_tracker.db")


def _build_connect_args(url: str) -> dict[str, object]:
    """Driver-specific connect args (PostgreSQL timeout avoids infinite hang on bad DNS/network)."""
    if url.startswith("postgresql"):
        return {"connect_timeout": int(os.getenv("DB_CONNECT_TIMEOUT", "10"))}
    return {}


engine = create_engine(
    DATABASE_URL,
    connect_args=_build_connect_args(DATABASE_URL),
    pool_pre_ping=True,
)


def get_session():
    """Yield a database session."""
    with Session(engine) as session:
        yield session
