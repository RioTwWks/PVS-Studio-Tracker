"""Database engine and session management."""

import os

from sqlmodel import Session, create_engine

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./pvs_tracker.db")

engine = create_engine(DATABASE_URL)


def get_session():
    """Yield a database session."""
    with Session(engine) as session:
        yield session
