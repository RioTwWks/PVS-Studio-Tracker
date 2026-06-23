"""Background startup state for readiness probes (avoids circular imports)."""

from __future__ import annotations

import threading

_init_done = threading.Event()
_init_error: BaseException | None = None


def mark_startup_finished(error: BaseException | None = None) -> None:
    """Mark DB migration/seed complete (or failed)."""
    global _init_error
    _init_error = error
    _init_done.set()


def startup_initialization_complete() -> bool:
    """True when background startup finished without error."""
    return _init_done.is_set() and _init_error is None


def startup_initialization_error() -> BaseException | None:
    return _init_error
