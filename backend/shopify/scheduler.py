"""Keep connected stores fresh: run an incremental sync of every store on a timer (inside the API process)."""
from __future__ import annotations

import logging
import threading

from . import sync

log = logging.getLogger("marginai.sync")


class SyncScheduler:
    def __init__(self, database_url: str, interval_minutes: float, first_delay_s: float = 5.0):
        self.database_url, self.interval, self.first_delay = database_url, interval_minutes * 60, first_delay_s
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="shopify-sync", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        wait = self.first_delay
        while not self._stop.wait(wait):
            try:
                for r in sync.sync_all(self.database_url):
                    log.info("sync: %s", r)
            except Exception:  # a failed round must never kill the scheduler
                log.exception("sync round failed")
            wait = self.interval
