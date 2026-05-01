import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Application configuration loaded from environment variables."""

    # Flask
    SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "dev-secret-key")
    HOST = os.getenv("FLASK_HOST", "0.0.0.0")
    PORT = int(os.getenv("FLASK_PORT", "5000"))
    DEBUG = os.getenv("FLASK_DEBUG", "false").lower() == "true"

    # Cisco CUCM
    CUCM_HOST = os.getenv("CUCM_HOST", "cucm.example.com")
    CUCM_USERNAME = os.getenv("CUCM_USERNAME", "admin")
    CUCM_PASSWORD = os.getenv("CUCM_PASSWORD", "")
    CUCM_VERSION = os.getenv("CUCM_VERSION", "14.0")
    CUCM_VERIFY_SSL = os.getenv("CUCM_VERIFY_SSL", "false").lower() == "true"

    # CTI Route Point
    CTI_ROUTE_POINT_DN = os.getenv("CTI_ROUTE_POINT_DN", "5000")
    CTI_DEVICE_NAME = os.getenv("CTI_DEVICE_NAME", "ClockInRoutePoint")

    # UKG
    UKG_BASE_URL = os.getenv("UKG_BASE_URL", "")
    UKG_API_KEY = os.getenv("UKG_API_KEY", "")
    UKG_CLIENT_ID = os.getenv("UKG_CLIENT_ID", "")
    UKG_CLIENT_SECRET = os.getenv("UKG_CLIENT_SECRET", "")
    UKG_USERNAME = os.getenv("UKG_USERNAME", "")
    UKG_PASSWORD = os.getenv("UKG_PASSWORD", "")
    UKG_USER_API_KEY = os.getenv("UKG_USER_API_KEY", "")

    # SSO / OAuth2
    SSO_ENABLED = os.getenv("SSO_ENABLED", "false").lower() == "true"
    SSO_PROVIDER_NAME = os.getenv("SSO_PROVIDER_NAME", "oauth")
    SSO_CLIENT_ID = os.getenv("SSO_CLIENT_ID", "")
    SSO_CLIENT_SECRET = os.getenv("SSO_CLIENT_SECRET", "")
    SSO_DISCOVERY_URL = os.getenv("SSO_DISCOVERY_URL", "")
    SSO_AUTHORIZATION_ENDPOINT = os.getenv("SSO_AUTHORIZATION_ENDPOINT", "")
    SSO_TOKEN_ENDPOINT = os.getenv("SSO_TOKEN_ENDPOINT", "")
    SSO_USERINFO_ENDPOINT = os.getenv("SSO_USERINFO_ENDPOINT", "")
    SSO_SCOPES = os.getenv("SSO_SCOPES", "openid email profile")
    SSO_ALLOWED_DOMAINS = os.getenv("SSO_ALLOWED_DOMAINS", "")
    SSO_ALLOWED_EMAILS = os.getenv("SSO_ALLOWED_EMAILS", "")
    SSO_ADMIN_ROLE_CLAIM = os.getenv("SSO_ADMIN_ROLE_CLAIM", "")

    # Machine-to-machine authentication for /ivr, /webhook, /api endpoints.
    API_AUTH_ENABLED = os.getenv("API_AUTH_ENABLED", "false").lower() == "true"

    # Session
    SESSION_TIMEOUT_MINUTES = int(os.getenv("SESSION_TIMEOUT_MINUTES", "480"))

    # Timezone for display purposes (IANA name, e.g. "America/New_York")
    TIMEZONE = os.getenv("TIMEZONE", "UTC")

    # Employee PIN requirement on phone IVR
    REQUIRE_EMPLOYEE_PIN = os.getenv("REQUIRE_EMPLOYEE_PIN", "false").lower() == "true"

    # Database
    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///clock_records.db")

    # Logging
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
