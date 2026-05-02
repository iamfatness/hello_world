"""Tests for security hardening, audit logging, and new features."""

import datetime
import hashlib
import pytest
from app import create_app
from models.database import Employee, TimePunch, AuditLog


class TestConfig:
    SECRET_KEY = "test-secret"
    HOST = "localhost"
    PORT = 5000
    DEBUG = False
    CUCM_HOST = "test-cucm"
    CUCM_USERNAME = "admin"
    CUCM_PASSWORD = "password"
    CUCM_VERSION = "14.0"
    CUCM_VERIFY_SSL = False
    CTI_ROUTE_POINT_DN = "5000"
    CTI_DEVICE_NAME = "TestRoutePoint"
    UKG_BASE_URL = "https://test-ukg.example.com"
    UKG_API_KEY = "test-key"
    UKG_CLIENT_ID = "test-client"
    UKG_CLIENT_SECRET = "test-secret"
    UKG_USERNAME = "test-user"
    UKG_PASSWORD = "test-pass"
    UKG_USER_API_KEY = "test-user-key"
    DATABASE_URL = "sqlite:///:memory:"
    LOG_LEVEL = "DEBUG"
    REQUIRE_EMPLOYEE_PIN = False
    TIMEZONE = "America/New_York"


class PinConfig(TestConfig):
    REQUIRE_EMPLOYEE_PIN = True


def _make_app(config_cls=TestConfig, pin=None):
    app = create_app(config=config_cls)
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False

    session = app.config["DB_SESSION_FACTORY"]()
    emp = Employee(
        employee_id="EMP001",
        name="Test User",
        phone_extension="1001",
        caller_id="5551234567",
        ukg_employee_id="UKG001",
        pin_hash=hashlib.sha256(pin.encode()).hexdigest() if pin else None,
    )
    session.add(emp)
    session.commit()
    session.close()
    return app


@pytest.fixture
def app():
    application = _make_app()
    yield application
    worker = application.config.get("RETRY_WORKER")
    if worker:
        worker.stop()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def app_with_pin():
    application = _make_app(PinConfig, pin="1234")
    yield application
    worker = application.config.get("RETRY_WORKER")
    if worker:
        worker.stop()


@pytest.fixture
def client_pin(app_with_pin):
    return app_with_pin.test_client()


# ---- CSRF ----

def test_csrf_blocks_post_without_token():
    """When CSRF is enabled, POST without token is rejected."""
    app = create_app(config=TestConfig)
    app.config["TESTING"] = False
    app.config["WTF_CSRF_ENABLED"] = True
    client = app.test_client()

    resp = client.post("/admin/config/save", data={"ukg_base_url": "x"})
    assert resp.status_code == 400

    worker = app.config.get("RETRY_WORKER")
    if worker:
        worker.stop()


# ---- Session timeout ----

def test_session_timeout_configured(app):
    assert app.config["PERMANENT_SESSION_LIFETIME"] == datetime.timedelta(minutes=480)


# ---- Timezone ----

def test_timezone_in_config(app):
    assert app.config["TIMEZONE"] == "America/New_York"


def test_ivr_menu_serves_ok(client):
    resp = client.get("/ivr/menu")
    assert resp.status_code == 200


def test_punch_shows_local_time(client):
    resp = client.get("/ivr/authenticate?type=clock_in&employee_id=EMP001")
    assert resp.status_code == 200
    # Should contain time in AM/PM format
    assert b":" in resp.data


# ---- Duplicate punch detection ----

def test_duplicate_punch_blocked(client):
    # First clock in succeeds
    resp = client.get("/ivr/authenticate?type=clock_in&employee_id=EMP001")
    assert resp.status_code == 200
    assert b"Success" in resp.data or b"Error" in resp.data

    # Second clock in of same type blocked
    resp = client.get("/ivr/authenticate?type=clock_in&employee_id=EMP001")
    assert resp.status_code == 200
    assert b"Already Recorded" in resp.data


def test_different_punch_type_not_blocked(client):
    # Clock in
    client.get("/ivr/authenticate?type=clock_in&employee_id=EMP001")
    # Clock out - different type, should succeed
    resp = client.get("/ivr/authenticate?type=clock_out&employee_id=EMP001")
    assert resp.status_code == 200
    assert b"Already Recorded" not in resp.data


# ---- PIN authentication ----

def test_pin_prompt_shown_when_enabled(client_pin):
    """When PIN is required, entering employee ID shows PIN prompt."""
    resp = client_pin.get("/ivr/authenticate?type=clock_in&employee_id=EMP001")
    assert resp.status_code == 200
    assert b"Enter PIN" in resp.data


def test_pin_correct_allows_punch(client_pin):
    resp = client_pin.get(
        "/ivr/verify-pin?employee_id=EMP001&type=clock_in&pin=1234"
    )
    assert resp.status_code == 200
    assert b"Success" in resp.data or b"Error" in resp.data
    assert b"Invalid PIN" not in resp.data


def test_pin_incorrect_rejects(client_pin):
    resp = client_pin.get(
        "/ivr/verify-pin?employee_id=EMP001&type=clock_in&pin=9999"
    )
    assert resp.status_code == 200
    assert b"Invalid PIN" in resp.data


def test_pin_missing_rejects(client_pin):
    resp = client_pin.get(
        "/ivr/verify-pin?employee_id=EMP001&type=clock_in&pin="
    )
    assert resp.status_code == 200
    assert b"Missing" in resp.data or b"Invalid" in resp.data or b"No PIN" in resp.data


def test_caller_id_with_pin_shows_prompt(client_pin):
    """Auto-identified caller still gets PIN prompt when required."""
    resp = client_pin.get("/ivr/punch?type=clock_in&callerid=5551234567")
    assert resp.status_code == 200
    assert b"Enter PIN" in resp.data


# ---- Audit logging ----

def test_audit_log_on_add_employee(client, app):
    client.post("/admin/employees/add", data={
        "employee_id": "EMP002",
        "name": "Audit Test",
        "ukg_employee_id": "UKG002",
    })
    session = app.config["DB_SESSION_FACTORY"]()
    try:
        logs = session.query(AuditLog).filter(AuditLog.action == "employee.add").all()
        assert len(logs) == 1
        assert "EMP002" in logs[0].detail
    finally:
        session.close()


def test_audit_log_on_config_save(client, app):
    client.post("/admin/config/save", data={"ukg_base_url": "https://x.com"})
    session = app.config["DB_SESSION_FACTORY"]()
    try:
        logs = session.query(AuditLog).filter(AuditLog.action == "config.update").all()
        assert len(logs) >= 1
    finally:
        session.close()


def test_audit_log_page_loads(client):
    resp = client.get("/admin/audit-log")
    assert resp.status_code == 200
    assert b"Audit Log" in resp.data


# ---- CSV export ----

def test_csv_export_returns_csv(client):
    # Add a punch first
    client.get("/ivr/authenticate?type=clock_in&employee_id=EMP001")

    today = datetime.date.today().isoformat()
    resp = client.get(f"/admin/punches/export?date={today}")
    assert resp.status_code == 200
    assert resp.content_type == "text/csv; charset=utf-8"
    assert b"Employee ID" in resp.data
    assert b"EMP001" in resp.data


# ---- Health check ----

def test_health_check_has_details(client):
    resp = client.get("/webhook/health")
    data = resp.get_json()
    assert "checks" in data
    assert "database" in data["checks"]
    assert data["checks"]["database"] == "ok"


# ---- Employee PIN in admin UI ----

def test_add_employee_with_pin(client, app):
    resp = client.post("/admin/employees/add", data={
        "employee_id": "EMP_PIN",
        "name": "PIN User",
        "ukg_employee_id": "UKG_PIN",
        "pin": "5678",
    }, follow_redirects=True)
    assert resp.status_code == 200

    session = app.config["DB_SESSION_FACTORY"]()
    try:
        emp = session.query(Employee).filter_by(employee_id="EMP_PIN").first()
        assert emp is not None
        assert emp.pin_hash == hashlib.sha256(b"5678").hexdigest()
    finally:
        session.close()


def test_update_employee_pin(client, app):
    resp = client.post("/admin/employees/update", data={
        "employee_id": "EMP001",
        "name": "Test User",
        "ukg_employee_id": "UKG001",
        "pin": "4321",
    }, follow_redirects=True)
    assert resp.status_code == 200

    session = app.config["DB_SESSION_FACTORY"]()
    try:
        emp = session.query(Employee).filter_by(employee_id="EMP001").first()
        assert emp.pin_hash == hashlib.sha256(b"4321").hexdigest()
    finally:
        session.close()
