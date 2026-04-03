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
from routes.ivr import ivr_bp
from routes.webhooks import webhooks_bp
from routes.api import api_bp
from routes.admin import admin_bp


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

    # Register route blueprints
    app.register_blueprint(ivr_bp)
    app.register_blueprint(webhooks_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(admin_bp)

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
