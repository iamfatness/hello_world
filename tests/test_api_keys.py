"""Tests for machine-to-machine API key authentication."""

import pytest
from app import create_app
from auth.api_keys import create_api_key, generate_api_key, hash_key, verify_api_key
from models.database import ApiKey, Employee


class BaseTestConfig:
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
    API_AUTH_ENABLED = False
    SSO_ENABLED = False
    SSO_PROVIDER_NAME = "oauth"
    SSO_CLIENT_ID = ""
    SSO_CLIENT_SECRET = ""
    SSO_DISCOVERY_URL = ""
    SSO_AUTHORIZATION_ENDPOINT = ""
    SSO_TOKEN_ENDPOINT = ""
    SSO_USERINFO_ENDPOINT = ""
    SSO_SCOPES = "openid email profile"
    SSO_ALLOWED_DOMAINS = ""
    SSO_ALLOWED_EMAILS = ""
    SSO_ADMIN_ROLE_CLAIM = ""


class ApiAuthOffConfig(BaseTestConfig):
    API_AUTH_ENABLED = False


class ApiAuthOnConfig(BaseTestConfig):
    API_AUTH_ENABLED = True


class ApiAuthAndSsoOnConfig(BaseTestConfig):
    API_AUTH_ENABLED = True
    SSO_ENABLED = True
    SSO_CLIENT_ID = "test-sso-client"
    SSO_CLIENT_SECRET = "test-sso-secret"
    SSO_AUTHORIZATION_ENDPOINT = "https://idp.example.com/authorize"
    SSO_TOKEN_ENDPOINT = "https://idp.example.com/token"
    SSO_USERINFO_ENDPOINT = "https://idp.example.com/userinfo"
    SSO_ALLOWED_DOMAINS = "example.com"


def _seed_employee(application):
    session = application.config["DB_SESSION_FACTORY"]()
    try:
        emp = Employee(
            employee_id="EMP001",
            name="Test User",
            phone_extension="1001",
            caller_id="5551234567",
            ukg_employee_id="UKG001",
        )
        session.add(emp)
        session.commit()
    finally:
        session.close()


def _make_app(config_cls):
    application = create_app(config=config_cls)
    application.config["TESTING"] = True
    application.config["WTF_CSRF_ENABLED"] = False
    _seed_employee(application)
    return application


@pytest.fixture
def app_off():
    app = _make_app(ApiAuthOffConfig)
    yield app
    worker = app.config.get("RETRY_WORKER")
    if worker:
        worker.stop()


@pytest.fixture
def app_on():
    app = _make_app(ApiAuthOnConfig)
    yield app
    worker = app.config.get("RETRY_WORKER")
    if worker:
        worker.stop()


@pytest.fixture
def app_on_with_sso():
    app = _make_app(ApiAuthAndSsoOnConfig)
    yield app
    worker = app.config.get("RETRY_WORKER")
    if worker:
        worker.stop()


def _create_key(app, name="Test Key"):
    session = app.config["DB_SESSION_FACTORY"]()
    try:
        plaintext, _ = create_api_key(session, name=name, created_by="test")
        return plaintext
    finally:
        session.close()


# ---- Unit tests for helpers ----

def test_generate_api_key_has_prefix_and_length():
    key = generate_api_key()
    assert key.startswith("ckuk_")
    assert len(key) == 5 + 32


def test_hash_is_deterministic():
    assert hash_key("abc") == hash_key("abc")
    assert hash_key("abc") != hash_key("abcd")


def test_verify_api_key_roundtrip(app_off):
    session = app_off.config["DB_SESSION_FACTORY"]()
    try:
        plaintext, _ = create_api_key(session, name="Roundtrip", created_by="test")
        verified = verify_api_key(session, plaintext)
        assert verified is not None
        assert verified.name == "Roundtrip"
        assert verified.last_used_at is not None
    finally:
        session.close()


def test_verify_api_key_rejects_unknown(app_off):
    session = app_off.config["DB_SESSION_FACTORY"]()
    try:
        assert verify_api_key(session, "ckuk_not-a-real-key") is None
        assert verify_api_key(session, "") is None
    finally:
        session.close()


def test_verify_api_key_rejects_revoked(app_off):
    session = app_off.config["DB_SESSION_FACTORY"]()
    try:
        plaintext, key = create_api_key(session, name="Revoked", created_by="test")
        key.revoked = True
        session.commit()
        assert verify_api_key(session, plaintext) is None
    finally:
        session.close()


def test_plaintext_is_not_stored(app_off):
    session = app_off.config["DB_SESSION_FACTORY"]()
    try:
        plaintext, key = create_api_key(session, name="Storage", created_by="test")
        rows = session.query(ApiKey).all()
        assert len(rows) == 1
        assert rows[0].key_hash != plaintext
        assert rows[0].key_prefix == plaintext[:8]
    finally:
        session.close()


# ---- Endpoint tests: API auth disabled (default) ----

def test_ivr_open_when_auth_disabled(app_off):
    client = app_off.test_client()
    resp = client.get("/ivr/menu")
    assert resp.status_code == 200


def test_webhook_open_when_auth_disabled(app_off):
    client = app_off.test_client()
    resp = client.get("/webhook/call?callerid=5551234567&callednumber=5000")
    assert resp.status_code == 200


def test_api_open_when_auth_disabled(app_off):
    client = app_off.test_client()
    resp = client.get("/api/employees")
    assert resp.status_code == 200


# ---- Endpoint tests: API auth enabled ----

def test_ivr_rejected_without_key(app_on):
    client = app_on.test_client()
    resp = client.get("/ivr/menu")
    assert resp.status_code == 401
    assert b"Authentication required" in resp.data


def test_webhook_call_rejected_without_key(app_on):
    client = app_on.test_client()
    resp = client.get("/webhook/call?callerid=5551234567&callednumber=5000")
    assert resp.status_code == 401


def test_api_rejected_without_key(app_on):
    client = app_on.test_client()
    resp = client.get("/api/employees")
    assert resp.status_code == 401


def test_health_check_stays_open_with_auth_enabled(app_on):
    """Monitoring systems must be able to reach /webhook/health without a key."""
    client = app_on.test_client()
    resp = client.get("/webhook/health")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "healthy"


def test_ivr_accepts_header_key(app_on):
    key = _create_key(app_on)
    client = app_on.test_client()
    resp = client.get("/ivr/menu", headers={"X-API-Key": key})
    assert resp.status_code == 200
    assert b"CiscoIPPhoneMenu" in resp.data


def test_ivr_accepts_query_key(app_on):
    key = _create_key(app_on)
    client = app_on.test_client()
    resp = client.get(f"/ivr/menu?api_key={key}")
    assert resp.status_code == 200


def test_webhook_accepts_query_key(app_on):
    key = _create_key(app_on)
    client = app_on.test_client()
    resp = client.get(
        f"/webhook/call?callerid=5551234567&callednumber=5000&api_key={key}"
    )
    assert resp.status_code == 200


def test_api_accepts_header_key(app_on):
    key = _create_key(app_on)
    client = app_on.test_client()
    resp = client.get("/api/employees", headers={"X-API-Key": key})
    assert resp.status_code == 200
    assert len(resp.get_json()) == 1


def test_invalid_key_rejected(app_on):
    _create_key(app_on)
    client = app_on.test_client()
    resp = client.get("/api/employees", headers={"X-API-Key": "ckuk_wrong"})
    assert resp.status_code == 401
    assert b"Invalid" in resp.data


def test_revoked_key_rejected(app_on):
    """Revoking a key takes effect on the next request."""
    key = _create_key(app_on, name="Retiring")
    client = app_on.test_client()

    resp = client.get("/api/employees", headers={"X-API-Key": key})
    assert resp.status_code == 200

    # Revoke it
    session = app_on.config["DB_SESSION_FACTORY"]()
    try:
        row = session.query(ApiKey).filter_by(name="Retiring").first()
        row.revoked = True
        session.commit()
    finally:
        session.close()

    resp = client.get("/api/employees", headers={"X-API-Key": key})
    assert resp.status_code == 401


def test_last_used_timestamp_updated(app_on):
    key = _create_key(app_on, name="Timestamp")
    client = app_on.test_client()
    client.get("/api/employees", headers={"X-API-Key": key})

    session = app_on.config["DB_SESSION_FACTORY"]()
    try:
        row = session.query(ApiKey).filter_by(name="Timestamp").first()
        assert row.last_used_at is not None
    finally:
        session.close()


# ---- SSO session bypass ----

def test_sso_session_bypasses_api_key_check(app_on_with_sso):
    """Admins with an active SSO session can reach machine endpoints without a key."""
    client = app_on_with_sso.test_client()

    # Without session: blocked
    resp = client.get("/api/employees")
    assert resp.status_code == 401

    # With session: allowed
    with client.session_transaction() as sess:
        sess["user"] = {"email": "admin@example.com", "name": "Admin"}

    resp = client.get("/api/employees")
    assert resp.status_code == 200
