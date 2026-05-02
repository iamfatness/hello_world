"""IVR (Interactive Voice Response) routes for Cisco IP Phone XML Services.

These endpoints serve Cisco IP Phone XML documents that render menus,
input forms, and text screens on the phone's display. This is the primary
interface employees interact with when calling the clock-in line.

Flow:
1. Employee calls the CTI Route Point number
2. CUCM webhook hits /webhook/call -> redirects phone to /ivr/menu
3. Phone displays the main menu (Clock In / Clock Out / Check Status)
4. Employee selects an option via softkeys
5. If not auto-identified by Caller ID, prompted to enter Employee ID
6. Punch is recorded locally and sent to UKG
7. Confirmation screen displayed on phone
"""

import datetime
import logging
import re

from flask import Blueprint, request, Response, current_app

from cisco.phone_services import (
    build_welcome_menu,
    build_employee_id_prompt,
    build_pin_prompt,
    build_confirmation_screen,
    build_status_screen,
)
from auth.api_keys import machine_auth_required

logger = logging.getLogger(__name__)
ivr_bp = Blueprint("ivr", __name__, url_prefix="/ivr")

_EMPLOYEE_ID_RE = re.compile(r'^[A-Za-z0-9]{1,20}$')
_PIN_RE = re.compile(r'^\d{4,20}$')
_VALID_PUNCH_TYPES = {"clock_in", "clock_out"}


def _validate_employee_id(employee_id):
    """Return error message string if invalid, else None."""
    if not employee_id:
        return "No Employee ID entered.\nPlease try again."
    if not _EMPLOYEE_ID_RE.match(employee_id):
        return "Invalid Employee ID format.\nUse up to 20 alphanumeric characters."
    return None


def _validate_pin(pin):
    """Return error message string if invalid, else None."""
    if not pin:
        return "No PIN entered.\nPlease try again."
    if not _PIN_RE.match(pin):
        return "Invalid PIN.\nPIN must be 4-20 digits."
    return None


def _validate_punch_type(punch_type):
    """Return error message string if invalid, else None."""
    if punch_type not in _VALID_PUNCH_TYPES:
        return "Invalid punch type."
    return None


@ivr_bp.before_request
def _require_machine_auth():
    """Require API key (or SSO session) for all /ivr endpoints."""
    return machine_auth_required()


def _xml_response(xml_bytes):
    """Return an XML response with the correct content type for Cisco phones."""
    return Response(xml_bytes, content_type="text/xml; charset=UTF-8")


def _format_local_time(utc_dt):
    """Convert a UTC datetime to the configured timezone for display."""
    from zoneinfo import ZoneInfo
    tz_name = current_app.config.get("TIMEZONE", "UTC")
    try:
        tz = ZoneInfo(tz_name)
    except (KeyError, Exception):
        tz = ZoneInfo("UTC")
    local_dt = utc_dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(tz)
    return local_dt.strftime("%I:%M %p")


@ivr_bp.route("/menu")
def main_menu():
    """Serve the main clock-in/clock-out menu to the phone."""
    app_url = current_app.config.get("APP_URL", request.host_url.rstrip("/"))
    return _xml_response(build_welcome_menu(app_url))


@ivr_bp.route("/punch")
def punch_prompt():
    """Prompt for employee ID before recording a punch.

    If the caller is already identified (via Caller ID lookup), skip the
    prompt and go directly to recording the punch (or PIN prompt if required).
    """
    punch_type = request.args.get("type", "clock_in")
    caller_id = request.args.get("callerid", "")
    app_url = current_app.config.get("APP_URL", request.host_url.rstrip("/"))

    # Try to auto-identify by caller ID
    if caller_id:
        cti = current_app.config["CTI_HANDLER"]
        result = cti.handle_incoming_call(caller_id, "")
        if result.get("recognized"):
            if current_app.config.get("REQUIRE_EMPLOYEE_PIN"):
                return _xml_response(
                    build_pin_prompt(app_url, result["employee_id"], punch_type, caller_id)
                )
            return _maybe_record_punch(result["employee_id"], punch_type, caller_id)

    return _xml_response(build_employee_id_prompt(app_url, punch_type))


@ivr_bp.route("/authenticate")
def authenticate_and_punch():
    """Validate the employee ID entered on the phone and record the punch."""
    employee_id = request.args.get("employee_id", "").strip()
    punch_type = request.args.get("type", "clock_in")
    caller_id = request.args.get("callerid", "")

    err = _validate_employee_id(employee_id) or _validate_punch_type(punch_type)
    if err:
        return _xml_response(build_confirmation_screen("Error", err))

    cti = current_app.config["CTI_HANDLER"]
    employee = cti.lookup_employee_by_id(employee_id)

    if not employee:
        logger.warning("Unknown employee ID entered: %s", employee_id)
        return _xml_response(
            build_confirmation_screen("Error", f"Employee ID {employee_id} not found.\nPlease try again.")
        )

    if current_app.config.get("REQUIRE_EMPLOYEE_PIN"):
        app_url = current_app.config.get("APP_URL", request.host_url.rstrip("/"))
        return _xml_response(
            build_pin_prompt(app_url, employee.employee_id, punch_type, caller_id)
        )

    return _maybe_record_punch(employee.employee_id, punch_type, caller_id)


@ivr_bp.route("/status")
def check_status():
    """Show the employee their current clock status.

    Requires employee_id param or caller ID auto-lookup.
    """
    employee_id = request.args.get("employee_id", "").strip()
    caller_id = request.args.get("callerid", "")
    app_url = current_app.config.get("APP_URL", request.host_url.rstrip("/"))

    # Try caller ID lookup first
    if not employee_id and caller_id:
        cti = current_app.config["CTI_HANDLER"]
        result = cti.handle_incoming_call(caller_id, "")
        if result.get("recognized"):
            employee_id = result["employee_id"]

    if not employee_id:
        # Need to prompt for ID - redirect to input form
        root_xml = build_employee_id_prompt(app_url, "status")
        return _xml_response(root_xml)

    return _show_status(employee_id)


@ivr_bp.route("/verify-pin")
def verify_pin():
    """Verify the employee's PIN and then record the punch."""
    import hashlib
    employee_id = request.args.get("employee_id", "").strip()
    punch_type = request.args.get("type", "clock_in")
    caller_id = request.args.get("callerid", "")
    pin = request.args.get("pin", "").strip()

    err = (_validate_employee_id(employee_id)
           or _validate_pin(pin)
           or _validate_punch_type(punch_type))
    if err:
        return _xml_response(build_confirmation_screen("Error", err))

    from models.database import Employee
    db_session = current_app.config["DB_SESSION_FACTORY"]()
    try:
        emp = db_session.query(Employee).filter(Employee.employee_id == employee_id).first()
        if not emp:
            return _xml_response(
                build_confirmation_screen("Error", "Employee not found.")
            )
        if not emp.pin_hash:
            return _xml_response(
                build_confirmation_screen("Error", "No PIN set.\nContact your administrator.")
            )
        if hashlib.sha256(pin.encode("utf-8")).hexdigest() != emp.pin_hash:
            logger.warning("Invalid PIN attempt for employee %s", employee_id)
            return _xml_response(
                build_confirmation_screen("Error", "Invalid PIN.\nPlease try again.")
            )
    finally:
        db_session.close()

    return _maybe_record_punch(employee_id, punch_type, caller_id)


def _maybe_record_punch(employee_id, punch_type, caller_id):
    """Check for duplicate punches before recording."""
    from models.database import TimePunch

    db_session = current_app.config["DB_SESSION_FACTORY"]()
    try:
        today = datetime.date.today()
        last_punch = (
            db_session.query(TimePunch)
            .filter(
                TimePunch.employee_id == employee_id,
                TimePunch.punch_time >= datetime.datetime.combine(today, datetime.time.min),
            )
            .order_by(TimePunch.punch_time.desc())
            .first()
        )
        if last_punch and last_punch.punch_type == punch_type:
            action = "Clock In" if punch_type == "clock_in" else "Clock Out"
            return _xml_response(
                build_confirmation_screen(
                    "Already Recorded",
                    f"You already have a {action}\nrecorded today at\n"
                    f"{last_punch.punch_time.strftime('%I:%M %p')}."
                )
            )
    finally:
        db_session.close()

    return _record_punch(employee_id, punch_type, caller_id)


def _record_punch(employee_id, punch_type, caller_id):
    """Record a time punch locally and sync to UKG.

    Args:
        employee_id: The employee's ID.
        punch_type: 'clock_in' or 'clock_out'.
        caller_id: The phone number that placed the call.

    Returns:
        XML response confirming the punch.
    """
    from models.database import TimePunch, Employee

    db_session = current_app.config["DB_SESSION_FACTORY"]()
    ukg_client = current_app.config["UKG_CLIENT"]

    try:
        # Look up UKG employee ID
        employee = (
            db_session.query(Employee)
            .filter(Employee.employee_id == employee_id)
            .first()
        )
        if not employee:
            return _xml_response(
                build_confirmation_screen("Error", "Employee not found in system.")
            )

        now = datetime.datetime.utcnow()

        # Create local record
        punch = TimePunch(
            employee_id=employee_id,
            punch_type=punch_type,
            punch_time=now,
            source_caller_id=caller_id,
            ukg_synced="pending",
        )
        db_session.add(punch)
        db_session.commit()

        # Submit to UKG
        try:
            ukg_client.submit_time_punch(
                employee_id=employee.ukg_employee_id,
                punch_type=punch_type,
                punch_time=now,
            )
            punch.ukg_synced = "success"
            db_session.commit()
            logger.info(
                "Punch recorded and synced to UKG: %s %s", employee_id, punch_type
            )
        except Exception as e:
            punch.ukg_synced = "failed"
            punch.ukg_response = str(e)[:500]
            db_session.commit()
            logger.error("UKG sync failed for %s: %s", employee_id, e)
            # Still show success to user - punch is recorded locally
            # and can be retried via the admin API

        action = "Clock In" if punch_type == "clock_in" else "Clock Out"
        time_str = _format_local_time(now)
        return _xml_response(
            build_confirmation_screen(
                "Success",
                f"{action} recorded for\n{employee.name}\nat {time_str}"
            )
        )
    except Exception as e:
        db_session.rollback()
        logger.exception("Error recording punch for %s: %s", employee_id, e)
        return _xml_response(
            build_confirmation_screen("Error", "System error.\nPlease try again or contact IT.")
        )
    finally:
        db_session.close()


def _show_status(employee_id):
    """Query and display the employee's current clock status."""
    from models.database import TimePunch, Employee

    db_session = current_app.config["DB_SESSION_FACTORY"]()
    try:
        employee = (
            db_session.query(Employee)
            .filter(Employee.employee_id == employee_id)
            .first()
        )
        if not employee:
            return _xml_response(
                build_confirmation_screen("Error", "Employee not found.")
            )

        today = datetime.date.today()
        last_punch = (
            db_session.query(TimePunch)
            .filter(
                TimePunch.employee_id == employee_id,
                TimePunch.punch_time >= datetime.datetime.combine(
                    today, datetime.time.min
                ),
            )
            .order_by(TimePunch.punch_time.desc())
            .first()
        )

        local_str = _format_local_time(last_punch.punch_time) if last_punch else None
        return _xml_response(
            build_status_screen(
                employee.name,
                last_punch.punch_type if last_punch else None,
                last_punch.punch_time if last_punch else None,
                local_time_str=local_str,
            )
        )
    finally:
        db_session.close()
