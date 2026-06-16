"""Embedded vs external worker runtime."""

from __future__ import annotations

import logging
import os
import signal
import threading
from typing import Optional

from pvs_tracker.rest_queue.types import ALL_SERVICES
from pvs_tracker.rest_queue.worker import ServiceWorker

logger = logging.getLogger(__name__)

_workers: list[ServiceWorker] = []
_external_stop = threading.Event()


def queue_mode() -> str:
    """embedded — воркеры в процессе uvicorn; external — отдельные процессы/контейнеры."""
    return os.getenv("REST_QUEUE_MODE", "embedded").strip().lower()


def poll_interval() -> float:
    return float(os.getenv("REST_QUEUE_POLL_INTERVAL", "1.0"))


def start_embedded_workers(services: Optional[tuple[str, ...]] = None) -> None:
    """Запуск воркеров при старте uvicorn (REST_QUEUE_MODE=embedded)."""
    if queue_mode() != "embedded":
        logger.info("REST queue embedded workers disabled (REST_QUEUE_MODE=%s)", queue_mode())
        return
    if _workers:
        return
    target_services = services or ALL_SERVICES
    interval = poll_interval()
    for service in target_services:
        worker = ServiceWorker(service, poll_interval=interval)
        worker.start()
        _workers.append(worker)
    logger.info("REST queue embedded workers started: %s", ", ".join(target_services))


def stop_embedded_workers() -> None:
    """Остановка воркеров при shutdown uvicorn."""
    for worker in _workers:
        worker.stop()
    for worker in _workers:
        worker.join(timeout=5.0)
    _workers.clear()


def run_external_workers(services: tuple[str, ...]) -> None:
    """Блокирующий цикл для отдельного процесса/контейнера воркера."""
    interval = poll_interval()
    workers = [ServiceWorker(service, poll_interval=interval) for service in services]
    for worker in workers:
        worker.start()

    def _shutdown(*_args: object) -> None:
        logger.info("REST queue external workers shutting down")
        _external_stop.set()
        for worker in workers:
            worker.stop()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)
    logger.info("REST queue external workers running: %s", ", ".join(services))
    _external_stop.wait()
    for worker in workers:
        worker.join(timeout=10.0)
