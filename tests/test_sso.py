"""Tests for SSO/OAuth2 authentication."""

import pytest
from app import create_app
from auth import check_user_authorized
from models.database import Employee


class SSODisabledConfig:
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


class SSOEnabledConfig(SSODisabledConfig):
    SSO_ENABLED = True
    SSO_CLIENT_ID = "test-sso-client"
    SSO_CLIENT_SECRET = "test-sso-secret"
    SSO_AUTHORIZATION_ENDPOINT = "https://idp.example.com/authorize"
    SSO_TOKEN_ENDPOINT = "https://idp.example.com/token"
    SSO_USERINFO_ENDPOINT = "https://idp.example.com/userinfo"
    SSO_ALLOWED_DOMAINS = "example.com"
    SSO_ALLOWED_EMAILS = ""


@pytest.fixture
def app_no_sso():
    application = create_app(config=SSODisabledConfig)
    application.config["TESTING"] = True
    yield application
    worker = application.config.get("RETRY_WORKER")
    if worker:
        worker.stop()


@pytest.fixture
def client_no_sso(app_no_sso):
    return app_no_sso.test_client()


@pytest.fixture
def app_sso():
    application = create_app(config=SSOEnabledConfig)
    application.config["TESTING"] = True
    yield application
    worker = application.config.get("RETRY_WORKER")
    if worker:
        worker.stop()


@pytest.fixture
def client_sso(app_sso):
    return app_sso.test_client()


# ---- SSO Disabled Tests ----

def test_admin_accessible_without_sso(client_no_sso):
    """When SSO is disabled, admin pages load without login."""
    resp = client_no_sso.get("/admin/")
    assert resp.status_code == 200
    assert b"Cisco-UKG Clock" in resp.data


def test_config_page_accessible_without_sso(client_no_sso):
    """Config page loads without login when SSO is off."""
    resp = client_no_sso.get("/admin/config")
    assert resp.status_code == 200
    assert b"Single Sign-On" in resp.data


def test_login_page_redirects_when_sso_disabled(client_no_sso):
    """Login page redirects to dashboard when SSO is off."""
    resp = client_no_sso.get("/auth/login-page")
    assert resp.status_code == 302
    assert "/admin/" in resp.headers["Location"]


# ---- SSO Enabled Tests ----

def test_admin_redirects_to_login_when_sso_enabled(client_sso):
    """When SSO is enabled, unauthenticated users are redirected to login."""
    resp = client_sso.get("/admin/")
    assert resp.status_code == 302
    assert "/auth/login" in resp.headers["Location"]


def test_config_redirects_when_sso_enabled(client_sso):
    resp = client_sso.get("/admin/config")
    assert resp.status_code == 302
    assert "/auth/login" in resp.headers["Location"]


def test_employees_redirects_when_sso_enabled(client_sso):
    resp = client_sso.get("/admin/employees")
    assert resp.status_code == 302


def test_punches_redirects_when_sso_enabled(client_sso):
    resp = client_sso.get("/admin/punches")
    assert resp.status_code == 302


def test_login_page_renders_when_sso_enabled(client_sso):
    """Login page renders with SSO button when enabled."""
    resp = client_sso.get("/auth/login-page")
    assert resp.status_code == 200
    assert b"Sign in with" in resp.data


def test_admin_accessible_with_session(client_sso):
    """When SSO is enabled, authenticated users can access admin pages."""
    with client_sso.session_transaction() as sess:
        sess["user"] = {
            "email": "admin@example.com",
            "name": "Admin User",
            "picture": "",
            "sub": "12345",
        }
    resp = client_sso.get("/admin/")
    assert resp.status_code == 200
    assert b"Cisco-UKG Clock" in resp.data


def test_logout_clears_session(client_sso):
    """Logout clears the user session and redirects to login."""
    with client_sso.session_transaction() as sess:
        sess["user"] = {"email": "admin@example.com", "name": "Admin"}
    resp = client_sso.get("/auth/logout")
    assert resp.status_code == 302
    assert "/auth/login-page" in resp.headers["Location"]

    # Verify session is cleared - admin should redirect to login
    resp = client_sso.get("/admin/")
    assert resp.status_code == 302
    assert "/auth/login" in resp.headers["Location"]


def test_navbar_shows_user_info(client_sso):
    """Navbar displays user name and logout link when logged in."""
    with client_sso.session_transaction() as sess:
        sess["user"] = {"email": "admin@example.com", "name": "Admin User"}
    resp = client_sso.get("/admin/")
    assert b"Admin User" in resp.data
    assert b"Logout" in resp.data


def test_ivr_not_affected_by_sso(client_sso):
    """Phone IVR endpoints remain accessible regardless of SSO."""
    resp = client_sso.get("/ivr/menu")
    assert resp.status_code == 200
    assert b"CiscoIPPhoneMenu" in resp.data


def test_webhook_not_affected_by_sso(client_sso):
    """Webhooks remain accessible regardless of SSO."""
    resp = client_sso.get("/webhook/health")
    assert resp.status_code == 200


def test_api_not_affected_by_sso(client_sso):
    """REST API endpoints remain accessible regardless of SSO."""
    resp = client_sso.get("/api/employees")
    assert resp.status_code == 200


# ---- Authorization checks ----

def test_check_user_authorized_allowed_domain():
    from auth import check_user_authorized
    app = create_app(config=SSOEnabledConfig)
    with app.app_context():
        allowed, _ = check_user_authorized({"email": "user@example.com"})
        assert allowed is True

        allowed, reason = check_user_authorized({"email": "user@other.com"})
        assert allowed is False
        assert "not allowed" in reason

    worker = app.config.get("RETRY_WORKER")
    if worker:
        worker.stop()


def test_check_user_authorized_allowed_emails():
    cfg = type("Cfg", (SSOEnabledConfig,), {
        "SSO_ALLOWED_DOMAINS": "",
        "SSO_ALLOWED_EMAILS": "admin@example.com,ops@example.com",
    })
    app = create_app(config=cfg)
    with app.app_context():
        allowed, _ = check_user_authorized({"email": "admin@example.com"})
        assert allowed is True

        allowed, reason = check_user_authorized({"email": "random@example.com"})
        assert allowed is False
        assert "not in the allowed list" in reason

    worker = app.config.get("RETRY_WORKER")
    if worker:
        worker.stop()


def test_check_user_authorized_role_claim():
    cfg = type("Cfg", (SSOEnabledConfig,), {
        "SSO_ALLOWED_DOMAINS": "",
        "SSO_ADMIN_ROLE_CLAIM": "roles",
    })
    app = create_app(config=cfg)
    with app.app_context():
        allowed, _ = check_user_authorized({"email": "user@example.com", "roles": ["admin"]})
        assert allowed is True

        allowed, reason = check_user_authorized({"email": "user@example.com", "roles": ["viewer"]})
        assert allowed is False
        assert "admin role" in reason

    worker = app.config.get("RETRY_WORKER")
    if worker:
        worker.stop()


def test_sso_config_visible_on_config_page(client_no_sso):
    """SSO configuration section appears on the config page."""
    resp = client_no_sso.get("/admin/config")
    assert resp.status_code == 200
    assert b"Single Sign-On" in resp.data
    assert b"sso_client_id" in resp.data
    assert b"sso_discovery_url" in resp.data
    assert b"callback" in resp.data.lower()
