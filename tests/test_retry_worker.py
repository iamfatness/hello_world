"""Tests for the UKG retry worker."""

import datetime
from unittest.mock import MagicMock, patch

from models.database import init_db, Employee, TimePunch
from ukg.retry_worker import RetryWorker


def _setup_db():
    session_factory = init_db("sqlite:///:memory:")
    session = session_factory()
    session.add(Employee(
        employee_id="EMP001", name="Test", ukg_employee_id="UKG001"
    ))
    session.add(TimePunch(
        employee_id="EMP001",
        punch_type="clock_in",
        punch_time=datetime.datetime.utcnow(),
        ukg_synced="failed",
        retry_count=0,
    ))
    session.commit()
    session.close()
    return session_factory


def test_process_failed_punches_success():
    session_factory = _setup_db()
    ukg = MagicMock()
    ukg.submit_punch_batch.return_value = [{"status": "accepted", "punchId": "p1"}]

    worker = RetryWorker(session_factory, ukg)
    worker._process_failed_punches()

    assert worker.stats["total_retried"] == 1
    assert worker.stats["total_succeeded"] == 1

    session = session_factory()
    punch = session.query(TimePunch).first()
    assert punch.ukg_synced == "success"
    session.close()


def test_process_failed_punches_failure():
    session_factory = _setup_db()
    ukg = MagicMock()
    ukg.submit_punch_batch.side_effect = Exception("UKG down")

    worker = RetryWorker(session_factory, ukg)
    worker._process_failed_punches()

    assert worker.stats["total_retried"] == 1
    assert worker.stats["total_succeeded"] == 0

    session = session_factory()
    punch = session.query(TimePunch).first()
    assert punch.ukg_synced == "failed"
    assert punch.retry_count == 1
    assert "UKG down" in punch.ukg_response
    session.close()


def test_worker_start_stop():
    session_factory = _setup_db()
    ukg = MagicMock()
    worker = RetryWorker(session_factory, ukg)

    worker.start()
    assert worker.stats["running"] is True

    worker.stop()
    assert worker.stats["running"] is False


def test_get_stats():
    session_factory = _setup_db()
    ukg = MagicMock()
    worker = RetryWorker(session_factory, ukg)

    stats = worker.get_stats()
    assert "total_retried" in stats
    assert "running" in stats


def test_exponential_backoff_skips_recent_retries():
    """Punches retried recently should be skipped based on backoff schedule."""
    session_factory = _setup_db()

    # Set last_retry_at to just now - should be skipped
    session = session_factory()
    punch = session.query(TimePunch).first()
    punch.last_retry_at = datetime.datetime.utcnow()
    punch.retry_count = 1
    session.commit()
    session.close()

    ukg = MagicMock()
    worker = RetryWorker(session_factory, ukg)
    worker._process_failed_punches()

    # Should NOT have retried because backoff hasn't elapsed
    ukg.submit_punch_batch.assert_not_called()
