"""Background retry worker for failed UKG time punch syncs.

Runs as a daemon thread alongside the Flask application. Periodically
scans for punches that failed to sync to UKG and retries them with
exponential backoff.

Retry schedule: 30s, 1m, 2m, 5m, 15m, 30m, 1h (then hourly up to max retries).
"""

import datetime
import logging
import threading
import time

logger = logging.getLogger(__name__)

RETRY_INTERVALS = [30, 60, 120, 300, 900, 1800, 3600]
MAX_RETRIES = 48
POLL_INTERVAL = 30  # seconds between scans


class RetryWorker:
    """Background worker that retries failed UKG punch submissions."""

    def __init__(self, db_session_factory, ukg_client):
        self.db_session_factory = db_session_factory
        self.ukg_client = ukg_client
        self._stop_event = threading.Event()
        self._thread = None
        self.stats = {
            "total_retried": 0,
            "total_succeeded": 0,
            "total_exhausted": 0,
            "last_run": None,
            "running": False,
        }

    def start(self):
        """Start the background retry thread."""
        if self._thread and self._thread.is_alive():
            logger.warning("Retry worker already running")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self.stats["running"] = True
        logger.info("Retry worker started (poll every %ds)", POLL_INTERVAL)

    def stop(self):
        """Signal the worker to stop."""
        self._stop_event.set()
        self.stats["running"] = False
        if self._thread:
            self._thread.join(timeout=10)
        logger.info("Retry worker stopped")

    def _run_loop(self):
        """Main loop: sleep, then process failed punches."""
        while not self._stop_event.is_set():
            try:
                self._process_failed_punches()
            except Exception:
                logger.exception("Error in retry worker loop")

            self._stop_event.wait(timeout=POLL_INTERVAL)

    def _process_failed_punches(self):
        """Find and retry all eligible failed punches."""
        from models.database import TimePunch, Employee

        session = self.db_session_factory()
        try:
            failed = (
                session.query(TimePunch)
                .filter(
                    TimePunch.ukg_synced.in_(["failed", "pending"]),
                    TimePunch.retry_count < MAX_RETRIES,
                )
                .all()
            )

            now = datetime.datetime.utcnow()
            self.stats["last_run"] = now.isoformat()

            for punch in failed:
                # Check if enough time has passed since last retry
                if punch.last_retry_at:
                    idx = min(punch.retry_count, len(RETRY_INTERVALS) - 1)
                    wait_seconds = RETRY_INTERVALS[idx]
                    next_retry = punch.last_retry_at + datetime.timedelta(
                        seconds=wait_seconds
                    )
                    if now < next_retry:
                        continue

                employee = (
                    session.query(Employee)
                    .filter(Employee.employee_id == punch.employee_id)
                    .first()
                )
                if not employee:
                    continue

                try:
                    self.ukg_client.submit_time_punch(
                        employee_id=employee.ukg_employee_id,
                        punch_type=punch.punch_type,
                        punch_time=punch.punch_time,
                    )
                    punch.ukg_synced = "success"
                    punch.ukg_response = None
                    punch.last_retry_at = now
                    session.commit()
                    self.stats["total_retried"] += 1
                    self.stats["total_succeeded"] += 1
                    logger.info(
                        "Retry succeeded for punch %d (employee %s)",
                        punch.id, punch.employee_id,
                    )
                except Exception as e:
                    punch.retry_count += 1
                    punch.last_retry_at = now
                    punch.ukg_response = str(e)[:500]
                    if punch.retry_count >= MAX_RETRIES:
                        self.stats["total_exhausted"] += 1
                        logger.error(
                            "Punch %d exhausted all %d retries",
                            punch.id, MAX_RETRIES,
                        )
                    session.commit()
                    self.stats["total_retried"] += 1
                    logger.warning(
                        "Retry %d/%d failed for punch %d: %s",
                        punch.retry_count, MAX_RETRIES, punch.id, e,
                    )
        finally:
            session.close()

    def get_stats(self):
        """Return current retry worker statistics."""
        return dict(self.stats)
