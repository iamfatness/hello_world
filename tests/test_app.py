"""Integration tests for the Flask application."""

import json
import pytest
from lxml import etree

from app import create_app
from models.database import Base, Employee, TimePunch, init_db


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

    # Seed a test employee
    session = application.config["DB_SESSION_FACTORY"]()
    emp = Employee(
        employee_id="EMP001",
        name="Test User",
        phone_extension="1001",
        caller_id="5551234567",
        ukg_employee_id="UKG001",
    )
    session.add(emp)
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


def test_index(client):
    resp = client.get("/")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["service"] == "Cisco-UKG Clock Integration"


def test_health_check(client):
    resp = client.get("/webhook/health")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "healthy"


def test_ivr_menu(client):
    resp = client.get("/ivr/menu")
    assert resp.status_code == 200
    assert b"CiscoIPPhoneMenu" in resp.data


def test_punch_prompt_unknown_caller(client):
    resp = client.get("/ivr/punch?type=clock_in")
    assert resp.status_code == 200
    xml = etree.fromstring(resp.data)
    assert xml.tag == "CiscoIPPhoneInput"


def test_authenticate_missing_id(client):
    resp = client.get("/ivr/authenticate?type=clock_in&employee_id=")
    assert resp.status_code == 200
    assert b"No Employee ID" in resp.data


def test_authenticate_unknown_id(client):
    resp = client.get("/ivr/authenticate?type=clock_in&employee_id=UNKNOWN")
    assert resp.status_code == 200
    assert b"not found" in resp.data


def test_authenticate_valid_employee(client):
    resp = client.get("/ivr/authenticate?type=clock_in&employee_id=EMP001")
    assert resp.status_code == 200
    # Should show success (UKG sync will fail but punch is recorded locally)
    xml = etree.fromstring(resp.data)
    assert xml.tag == "CiscoIPPhoneText"
    assert xml.find("Title").text in ("Success", "Error")


def test_webhook_incoming_call_known(client):
    resp = client.get("/webhook/call?callerid=5551234567&callednumber=5000")
    assert resp.status_code == 200
    xml = etree.fromstring(resp.data)
    # Known caller gets the menu
    assert xml.tag == "CiscoIPPhoneMenu"


def test_webhook_incoming_call_unknown(client):
    resp = client.get("/webhook/call?callerid=9999999999&callednumber=5000")
    assert resp.status_code == 200
    xml = etree.fromstring(resp.data)
    # Unknown caller gets prompted for ID
    assert xml.tag == "CiscoIPPhoneInput"


def test_api_list_employees(client):
    resp = client.get("/api/employees")
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data) == 1
    assert data[0]["employee_id"] == "EMP001"


def test_api_add_employee(client):
    resp = client.post(
        "/api/employees",
        data=json.dumps({
            "employee_id": "EMP002",
            "name": "New User",
            "ukg_employee_id": "UKG002",
            "caller_id": "5559876543",
        }),
        content_type="application/json",
    )
    assert resp.status_code == 201

    # Verify it was added
    resp = client.get("/api/employees")
    assert len(resp.get_json()) == 2


def test_api_add_duplicate_employee(client):
    resp = client.post(
        "/api/employees",
        data=json.dumps({
            "employee_id": "EMP001",
            "name": "Duplicate",
            "ukg_employee_id": "UKG001",
        }),
        content_type="application/json",
    )
    assert resp.status_code == 409


def test_api_delete_employee(client):
    resp = client.delete("/api/employees/EMP001")
    assert resp.status_code == 200

    resp = client.get("/api/employees")
    assert len(resp.get_json()) == 0


def test_api_delete_nonexistent(client):
    resp = client.delete("/api/employees/NOPE")
    assert resp.status_code == 404


def test_api_list_punches(client):
    resp = client.get("/api/punches")
    assert resp.status_code == 200
    assert isinstance(resp.get_json(), list)
