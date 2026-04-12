"""Cisco-UKG Clock Integration Application.

A Flask application that bridges Cisco IP phone systems with UKG Pro
Workforce Management for employee time tracking. Employees call a
designated phone number (CTI Route Point) and use the phone's display
to clock in/out. Punches are recorded locally and synced to UKG.

Usage:
    python app.py                  # Run with Flask dev server
    gunicorn app:create_app()      # Run with Gunicorn for production
"""

import atexit
import logging

from flask import Flask

from config import Config
from models.database import init_db, SystemConfig
from cisco.cti_handler import CTIHandler
from ukg.api_client import UKGApiClient
from ukg.retry_worker import RetryWorker
from auth import init_sso
from routes.ivr import ivr_bp
from routes.webhooks import webhooks_bp
from routes.api import api_bp
from routes.admin import admin_bp
from routes.auth_routes import auth_bp


def _load_db_config(session_factory, key, env_default):
    """Load a config value from the database, falling back to env default."""
    session = session_factory()
    try:
        row = session.query(SystemConfig).filter_by(config_key=key).first()
        return row.config_value if row and row.config_value else env_default
    finally:
        session.close()


def create_app(config=None):
    """Create and configure the Flask application.

    Args:
        config: Optional config object override (useful for testing).

    Returns:
        Configured Flask app instance.
    """
    app = Flask(__name__)

    # Load configuration
    cfg = config or Config
    app.config["SECRET_KEY"] = cfg.SECRET_KEY
    app.config["APP_URL"] = f"http://{cfg.HOST}:{cfg.PORT}"

    # Set up logging
    logging.basicConfig(
        level=getattr(logging, cfg.LOG_LEVEL, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger = logging.getLogger(__name__)
    logger.info("Initializing Cisco-UKG Clock application")

    # Initialize database
    db_session_factory = init_db(cfg.DATABASE_URL)
    app.config["DB_SESSION_FACTORY"] = db_session_factory

    # Initialize Cisco CTI handler
    cti_handler = CTIHandler(db_session_factory)
    app.config["CTI_HANDLER"] = cti_handler

    # Initialize UKG API client - prefer DB-saved config over env defaults
    ukg_client = UKGApiClient(
        base_url=_load_db_config(db_session_factory, "ukg_base_url", cfg.UKG_BASE_URL),
        api_key=_load_db_config(db_session_factory, "ukg_api_key", cfg.UKG_API_KEY),
        client_id=_load_db_config(db_session_factory, "ukg_client_id", cfg.UKG_CLIENT_ID),
        client_secret=_load_db_config(db_session_factory, "ukg_client_secret", cfg.UKG_CLIENT_SECRET),
        username=_load_db_config(db_session_factory, "ukg_username", cfg.UKG_USERNAME),
        password=_load_db_config(db_session_factory, "ukg_password", cfg.UKG_PASSWORD),
        user_api_key=_load_db_config(db_session_factory, "ukg_user_api_key", cfg.UKG_USER_API_KEY),
    )
    app.config["UKG_CLIENT"] = ukg_client

    # Start background retry worker for failed UKG syncs
    retry_worker = RetryWorker(db_session_factory, ukg_client)
    app.config["RETRY_WORKER"] = retry_worker
    retry_worker.start()
    atexit.register(retry_worker.stop)

    # Machine-to-machine API key authentication (ivr/webhook/api routes)
    app.config["API_AUTH_ENABLED"] = getattr(cfg, "API_AUTH_ENABLED", False)

    # SSO configuration
    app.config["SSO_ENABLED"] = getattr(cfg, "SSO_ENABLED", False)
    app.config["SSO_PROVIDER_NAME"] = getattr(cfg, "SSO_PROVIDER_NAME", "oauth")
    app.config["SSO_CLIENT_ID"] = getattr(cfg, "SSO_CLIENT_ID", "")
    app.config["SSO_CLIENT_SECRET"] = getattr(cfg, "SSO_CLIENT_SECRET", "")
    app.config["SSO_DISCOVERY_URL"] = getattr(cfg, "SSO_DISCOVERY_URL", "")
    app.config["SSO_AUTHORIZATION_ENDPOINT"] = getattr(cfg, "SSO_AUTHORIZATION_ENDPOINT", "")
    app.config["SSO_TOKEN_ENDPOINT"] = getattr(cfg, "SSO_TOKEN_ENDPOINT", "")
    app.config["SSO_USERINFO_ENDPOINT"] = getattr(cfg, "SSO_USERINFO_ENDPOINT", "")
    app.config["SSO_SCOPES"] = getattr(cfg, "SSO_SCOPES", "openid email profile")
    app.config["SSO_ALLOWED_DOMAINS"] = getattr(cfg, "SSO_ALLOWED_DOMAINS", "")
    app.config["SSO_ALLOWED_EMAILS"] = getattr(cfg, "SSO_ALLOWED_EMAILS", "")
    app.config["SSO_ADMIN_ROLE_CLAIM"] = getattr(cfg, "SSO_ADMIN_ROLE_CLAIM", "")

    # Load SSO overrides from DB
    sso_db_keys = [
        "sso_enabled", "sso_provider_name", "sso_client_id", "sso_client_secret",
        "sso_discovery_url", "sso_authorization_endpoint", "sso_token_endpoint",
        "sso_userinfo_endpoint", "sso_scopes", "sso_allowed_domains",
        "sso_allowed_emails", "sso_admin_role_claim",
    ]
    for key in sso_db_keys:
        db_val = _load_db_config(db_session_factory, key, "")
        if db_val:
            app_key = key.upper()
            if app_key == "SSO_ENABLED":
                app.config[app_key] = db_val.lower() == "true"
            else:
                app.config[app_key] = db_val

    # Load API auth toggle from DB
    api_auth_db = _load_db_config(db_session_factory, "api_auth_enabled", "")
    if api_auth_db:
        app.config["API_AUTH_ENABLED"] = api_auth_db.lower() == "true"

    # Initialize SSO
    init_sso(app)

    # Register route blueprints
    app.register_blueprint(ivr_bp)
    app.register_blueprint(webhooks_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(auth_bp)

    # Root endpoint redirects to admin dashboard
    @app.route("/")
    def index():
        return {
            "service": "Cisco-UKG Clock Integration",
            "version": "1.0.0",
            "admin_portal": "/admin/",
            "endpoints": {
                "admin": "/admin/",
                "ivr_menu": "/ivr/menu",
                "call_webhook": "/webhook/call",
                "health": "/webhook/health",
                "api_employees": "/api/employees",
                "api_punches": "/api/punches",
            },
        }

    logger.info("Application ready - listening on %s:%s", cfg.HOST, cfg.PORT)
    return app


if __name__ == "__main__":
    application = create_app()
    application.run(
        host=Config.HOST,
        port=Config.PORT,
        debug=Config.DEBUG,
    )
