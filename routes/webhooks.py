"""Webhook endpoints for receiving call events from Cisco CUCM.

CUCM can be configured to send HTTP requests when calls arrive at a
CTI Route Point. These webhooks receive those events and initiate
the IVR flow by redirecting the phone to the appropriate XML service URL.
"""

import logging
from flask import Blueprint, request, Response, current_app

from cisco.phone_services import build_welcome_menu, build_employee_id_prompt
from auth.api_keys import machine_auth_required

logger = logging.getLogger(__name__)
webhooks_bp = Blueprint("webhooks", __name__, url_prefix="/webhook")


@webhooks_bp.before_request
def _require_machine_auth():
    """Require API key (or SSO session) for webhook endpoints.

    The health check is exempted so external monitoring systems
    (load balancers, Nagios, Datadog, k8s probes) can reach it.
    """
    if request.endpoint == "webhooks.health_check":
        return None
    return machine_auth_required()


@webhooks_bp.route("/call", methods=["POST", "GET"])
def incoming_call():
    """Handle an incoming call event from CUCM.

    CUCM sends call data including caller ID (ANI) and called number (DNIS).
    We look up the caller and serve the appropriate phone XML screen.

    Expected parameters (via query string or POST form data):
        - callerid: The calling party number
        - callednumber: The dialed number (our route point DN)
        - devicename: The calling device name (optional)
    """
    caller_id = request.values.get("callerid", "")
    called_number = request.values.get("callednumber", "")
    device_name = request.values.get("devicename", "")

    logger.info(
        "Call webhook: caller=%s, called=%s, device=%s",
        caller_id, called_number, device_name
    )

    app_url = current_app.config.get("APP_URL", request.host_url.rstrip("/"))
    cti = current_app.config["CTI_HANDLER"]

    result = cti.handle_incoming_call(caller_id, called_number)

    if result.get("recognized"):
        # Known employee - show main menu directly
        xml = build_welcome_menu(app_url)
    else:
        # Unknown caller - prompt for employee ID
        xml = build_employee_id_prompt(app_url, "clock_in")

    return Response(xml, content_type="text/xml; charset=UTF-8")


@webhooks_bp.route("/health", methods=["GET"])
def health_check():
    """Health check endpoint for monitoring.

    Reports database reachability and retry worker status.
    """
    checks = {"database": "ok", "retry_worker": "ok"}
    healthy = True

    # Database check
    try:
        db = current_app.config["DB_SESSION_FACTORY"]()
        db.execute(__import__("sqlalchemy").text("SELECT 1"))
        db.close()
    except Exception:
        checks["database"] = "unreachable"
        healthy = False

    # Retry worker check
    worker = current_app.config.get("RETRY_WORKER")
    if worker:
        stats = worker.get_stats()
        if not stats.get("running"):
            checks["retry_worker"] = "stopped"
            healthy = False
    else:
        checks["retry_worker"] = "not configured"

    status_code = 200 if healthy else 503
    return {
        "status": "healthy" if healthy else "degraded",
        "service": "cisco-ukg-clock",
        "checks": checks,
    }, status_code
