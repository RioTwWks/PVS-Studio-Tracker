"""CLI entry point: python -m pvs_tracker.rest_queue --service jenkins"""

from __future__ import annotations

import argparse
import logging
import os

from pvs_tracker.rest_queue.runtime import run_external_workers
from pvs_tracker.rest_queue.types import ALL_SERVICES


def main() -> None:
    parser = argparse.ArgumentParser(description="PVS-Tracker REST queue worker")
    parser.add_argument(
        "--service",
        required=True,
        choices=[*ALL_SERVICES, "all"],
        help="Service to process (one worker thread per service)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.service == "all":
        services = ALL_SERVICES
    else:
        services = (args.service,)

    run_external_workers(services)


if __name__ == "__main__":
    main()
