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
BATCH_SIZE = 50     # punches per UKG API call


class RetryWorker:
    """Background worker that retries failed UKG punch submissions."""

    def __init__(self, db_session_factory, ukg_client, alert_callback=None):
        self.db_session_factory = db_session_factory
        self.ukg_client = ukg_client
        self._alert_callback = alert_callback
        self._stop_event = threading.Event()
        self._thread = None
        self.stats = {
            "total_retried": 0,
            "total_succeeded": 0,
            "total_exhausted": 0,
            "exhausted_punch_ids": [],
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
        """Find and retry all eligible failed/pending punches in batches."""
        from models.database import TimePunch, Employee

        session = self.db_session_factory()
        try:
            candidates = (
                session.query(TimePunch)
                .filter(
                    TimePunch.ukg_synced.in_(["failed", "pending"]),
                    TimePunch.retry_count < MAX_RETRIES,
                )
                .all()
            )

            now = datetime.datetime.utcnow()
            self.stats["last_run"] = now.isoformat()

            # Apply exponential backoff filter
            eligible = [p for p in candidates if self._is_due(p, now)]

            if not eligible:
                return

            # Load all required employees in one query
            emp_ids = {p.employee_id for p in eligible}
            employees = {
                e.employee_id: e
                for e in session.query(Employee)
                .filter(Employee.employee_id.in_(emp_ids))
                .all()
            }

            # Submit in batches of BATCH_SIZE
            for i in range(0, len(eligible), BATCH_SIZE):
                self._submit_batch(session, eligible[i:i + BATCH_SIZE], employees, now)
        finally:
            session.close()

    def _is_due(self, punch, now):
        """Return True if enough time has elapsed since the last retry attempt."""
        if not punch.last_retry_at:
            return True
        idx = min(punch.retry_count, len(RETRY_INTERVALS) - 1)
        next_retry = punch.last_retry_at + datetime.timedelta(seconds=RETRY_INTERVALS[idx])
        return now >= next_retry

    def _submit_batch(self, session, batch, employees, now):
        """Submit a slice of punches as a single UKG API call and persist results."""
        # Pair each punch with its UKG employee record; skip orphans
        records = [
            (punch, employees[punch.employee_id])
            for punch in batch
            if punch.employee_id in employees
        ]

        if not records:
            return

        punch_payloads = [
            {
                "employee_id": emp.ukg_employee_id,
                "punch_type": punch.punch_type,
                "punch_time": punch.punch_time,
            }
            for punch, emp in records
        ]

        try:
            results = self.ukg_client.submit_punch_batch(punch_payloads)

            for (punch, _), result in zip(records, results):
                self.stats["total_retried"] += 1
                if result.get("status") == "accepted":
                    punch.ukg_synced = "success"
                    punch.ukg_response = None
                    punch.last_retry_at = now
                    self.stats["total_succeeded"] += 1
                    logger.info("Batch retry succeeded for punch %d (employee %s)",
                                punch.id, punch.employee_id)
                else:
                    error_msg = result.get("error", "rejected by UKG")
                    punch.retry_count += 1
                    punch.last_retry_at = now
                    punch.ukg_response = str(error_msg)[:500]
                    self._check_exhaustion(punch)
                    logger.warning("Batch retry rejected for punch %d: %s",
                                   punch.id, error_msg)

            session.commit()

        except Exception as e:
            # Entire batch call failed — increment every punch in this slice
            for punch, _ in records:
                punch.retry_count += 1
                punch.last_retry_at = now
                punch.ukg_response = str(e)[:500]
                self.stats["total_retried"] += 1
                self._check_exhaustion(punch)
            session.commit()
            logger.warning("Batch of %d punches failed: %s", len(records), e)

    def _check_exhaustion(self, punch):
        """Handle a punch that may have reached its retry limit."""
        if punch.retry_count >= MAX_RETRIES:
            self.stats["total_exhausted"] += 1
            if punch.id not in self.stats["exhausted_punch_ids"]:
                self.stats["exhausted_punch_ids"].append(punch.id)
            logger.error(
                "Punch %d exhausted all %d retries for employee %s",
                punch.id, MAX_RETRIES, punch.employee_id,
            )
            self._fire_alert(punch)

    def _fire_alert(self, punch):
        """Invoke the alert callback when a punch exhausts all retries."""
        if self._alert_callback:
            try:
                self._alert_callback(punch)
            except Exception:
                logger.exception("Alert callback raised an exception for punch %d", punch.id)

    def get_stats(self):
        """Return current retry worker statistics."""
        return dict(self.stats)
