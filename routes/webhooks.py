"""Webhook endpoints for receiving call events from Cisco CUCM.

CUCM can be configured to send HTTP requests when calls arrive at a
CTI Route Point. These webhooks receive those events and initiate
the IVR flow by redirecting the phone to the appropriate XML service URL.
"""

import logging
from flask import Blueprint, request, Response, current_app

from cisco.phone_services import build_welcome_menu, build_employee_id_prompt

logger = logging.getLogger(__name__)
webhooks_bp = Blueprint("webhooks", __name__, url_prefix="/webhook")


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
    """Health check endpoint for monitoring."""
    return {"status": "healthy", "service": "cisco-ukg-clock"}
