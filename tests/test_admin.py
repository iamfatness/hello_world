"""Tests for the admin portal routes."""

import json
import datetime
import pytest

from app import create_app
from models.database import Employee, TimePunch, SystemConfig


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


@pytest.fixture
def app():
    application = create_app(config=TestConfig)
    application.config["TESTING"] = True
    application.config["WTF_CSRF_ENABLED"] = False

    session = application.config["DB_SESSION_FACTORY"]()
    emp = Employee(
        employee_id="EMP001",
        name="Test User",
        phone_extension="1001",
        caller_id="5551234567",
        ukg_employee_id="UKG001",
    )
    session.add(emp)
    punch = TimePunch(
        employee_id="EMP001",
        punch_type="clock_in",
        punch_time=datetime.datetime.utcnow(),
        ukg_synced="success",
        retry_count=0,
    )
    session.add(punch)
    session.commit()
    session.close()

    yield application

    # Stop retry worker
    worker = application.config.get("RETRY_WORKER")
    if worker:
        worker.stop()


@pytest.fixture
def client(app):
    return app.test_client()


def test_dashboard_loads(client):
    resp = client.get("/admin/")
    assert resp.status_code == 200
    assert b"Dashboard" in resp.data or b"Cisco-UKG Clock" in resp.data


def test_config_page_loads(client):
    resp = client.get("/admin/config")
    assert resp.status_code == 200
    assert b"UKG API Connection" in resp.data
    assert b"Cisco CUCM Connection" in resp.data


def test_save_config(client):
    resp = client.post("/admin/config/save", data={
        "ukg_base_url": "https://new-ukg.example.com",
        "ukg_api_key": "new-key",
        "ukg_client_id": "new-client",
        "ukg_client_secret": "new-secret",
        "ukg_username": "new-user",
        "ukg_password": "new-pass",
        "ukg_user_api_key": "new-ukey",
        "cucm_host": "new-cucm.example.com",
        "cucm_username": "admin2",
        "cucm_password": "pass2",
        "cucm_version": "15.0",
        "cti_route_point_dn": "6000",
        "cti_device_name": "NewRoutePoint",
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b"Configuration saved" in resp.data


def test_employees_page_loads(client):
    resp = client.get("/admin/employees")
    assert resp.status_code == 200
    assert b"Test User" in resp.data


def test_add_employee_via_admin(client):
    resp = client.post("/admin/employees/add", data={
        "employee_id": "EMP002",
        "name": "New Employee",
        "phone_extension": "1002",
        "caller_id": "5559876543",
        "ukg_employee_id": "UKG002",
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b"New Employee" in resp.data


def test_update_employee_via_admin(client):
    resp = client.post("/admin/employees/update", data={
        "employee_id": "EMP001",
        "name": "Updated Name",
        "phone_extension": "1001",
        "caller_id": "5551234567",
        "ukg_employee_id": "UKG001",
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b"Updated Name" in resp.data


def test_delete_employee_via_admin(client):
    resp = client.post("/admin/employees/EMP001/delete", follow_redirects=True)
    assert resp.status_code == 200
    assert b"removed" in resp.data


def test_punches_page_loads(client):
    resp = client.get("/admin/punches")
    assert resp.status_code == 200
    assert b"Time Punches" in resp.data


def test_add_manual_punch(client):
    now = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M")
    resp = client.post("/admin/punches/add", data={
        "employee_id": "EMP001",
        "punch_type": "clock_out",
        "punch_time": now,
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b"Manual punch recorded" in resp.data


def test_delete_punch(client, app):
    # Get the punch ID
    session = app.config["DB_SESSION_FACTORY"]()
    punch = session.query(TimePunch).first()
    punch_id = punch.id
    session.close()

    resp = client.post(f"/admin/punches/{punch_id}/delete", follow_redirects=True)
    assert resp.status_code == 200
    assert b"deleted" in resp.data


def test_dashboard_stats(client):
    resp = client.get("/admin/")
    assert resp.status_code == 200
    # Should show at least 1 employee and 1 punch
    assert b"Registered Employees" in resp.data
    assert b"Punches Today" in resp.data


def test_test_ukg_connection(client):
    resp = client.post("/admin/config/test-ukg")
    data = resp.get_json()
    # Will fail because it's a test URL, but should return structured response
    assert "success" in data


def test_test_cucm_connection(client):
    resp = client.post("/admin/config/test-cucm")
    data = resp.get_json()
    assert "success" in data
