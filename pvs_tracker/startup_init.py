"""CLI: python -m pvs_tracker.startup_init — sync DB init before uvicorn (Windows Docker)."""

from __future__ import annotations

import logging
import sys


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
        force=True,
    )
    print("Startup init: importing application modules...", flush=True)
    from pvs_tracker.main import _run_startup_init

    print("Startup init: running migrations and seed...", flush=True)
    _run_startup_init()
    print("Startup init: OK", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:
        print(f"Startup init FAILED: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1) from exc
