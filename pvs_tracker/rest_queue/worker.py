"""Background worker thread per external service."""

from __future__ import annotations

import logging
import threading
import uuid

from pvs_tracker.rest_queue.handlers import execute_job
from pvs_tracker.rest_queue.store import claim_next_job

logger = logging.getLogger(__name__)


class ServiceWorker(threading.Thread):
    """Один поток на service — последовательная обработка REST-вызовов."""

    def __init__(self, service: str, poll_interval: float = 1.0) -> None:
        super().__init__(name=f"rest-queue-{service}", daemon=True)
        self.service = service
        self.poll_interval = poll_interval
        self.worker_id = f"{service}-{uuid.uuid4().hex[:8]}"
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        logger.info("REST queue worker started service=%s id=%s", self.service, self.worker_id)
        while not self._stop.is_set():
            job = claim_next_job(self.service, self.worker_id)
            if job:
                execute_job(job)
            else:
                self._stop.wait(self.poll_interval)
        logger.info("REST queue worker stopped service=%s", self.service)
