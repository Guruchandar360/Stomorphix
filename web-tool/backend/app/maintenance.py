import os
import threading
import time
from pathlib import Path

from .analyzer import ANNOTATED_DIR, CSV_DIR, UPLOAD_DIR


OUTPUT_TTL_SECONDS = int(os.getenv("OUTPUT_TTL_SECONDS", str(24 * 60 * 60)))
CLEANUP_INTERVAL_SECONDS = int(os.getenv("CLEANUP_INTERVAL_SECONDS", "900"))


def cleanup_expired_files(directories, ttl_seconds=OUTPUT_TTL_SECONDS, now=None):
    cutoff = (time.time() if now is None else now) - ttl_seconds
    removed = 0
    for directory in directories:
        root = Path(directory).resolve()
        if not root.is_dir():
            continue
        for path in root.iterdir():
            try:
                resolved = path.resolve()
                if resolved.parent != root or not resolved.is_file() or resolved.stat().st_mtime >= cutoff:
                    continue
                resolved.unlink()
                removed += 1
            except OSError:
                continue
    return removed


class MaintenanceWorker:
    def __init__(self, batch_cleanup):
        self.batch_cleanup = batch_cleanup
        self.stop_event = threading.Event()
        self.worker = None

    def start(self):
        if self.worker and self.worker.is_alive():
            return
        self.stop_event.clear()
        self.run_once()
        self.worker = threading.Thread(target=self._loop, name="stomata-output-cleaner", daemon=True)
        self.worker.start()

    def stop(self):
        self.stop_event.set()
        if self.worker and self.worker.is_alive():
            self.worker.join(timeout=3)

    def run_once(self):
        cleanup_expired_files((UPLOAD_DIR, ANNOTATED_DIR, CSV_DIR))
        self.batch_cleanup()

    def _loop(self):
        while not self.stop_event.wait(CLEANUP_INTERVAL_SECONDS):
            self.run_once()
