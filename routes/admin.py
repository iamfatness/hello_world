"""Admin portal routes for the web-based management interface.

Provides pages for:
- Dashboard: system overview, stats, recent punches
- Configuration: UKG and CUCM connection settings
- Employees: CRUD management of employee roster
- Punches: view, correct, add, delete time punches
"""

import datetime
import logging

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash,
    current_app, jsonify, session,
)

from auth import login_required

logger = logging.getLogger(__name__)
admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


@admin_bp.before_request
def _require_login():
    """Apply login_required to all admin routes."""
    if not current_app.config.get("SSO_ENABLED"):
        return None
    user = session.get("user")
    if not user:
        session["next_url"] = request.url
        return redirect(url_for("auth.login"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_config_value(session, key, default=""):
    """Read a single config value from the database."""
    from models.database import SystemConfig
    row = session.query(SystemConfig).filter_by(config_key=key).first()
    return row.config_value if row else default


def _set_config_value(session, key, value):
    """Write a single config value to the database."""
    from models.database import SystemConfig
    row = session.query(SystemConfig).filter_by(config_key=key).first()
    if row:
        row.config_value = value
        row.updated_at = datetime.datetime.utcnow()
    else:
        session.add(SystemConfig(config_key=key, config_value=value))


def _load_all_config(session):
    """Load all configuration keys into a dict, falling back to env defaults."""
    from config import Config
    keys_defaults = {
        "ukg_base_url": Config.UKG_BASE_URL,
        "ukg_api_key": Config.UKG_API_KEY,
        "ukg_client_id": Config.UKG_CLIENT_ID,
        "ukg_client_secret": Config.UKG_CLIENT_SECRET,
        "ukg_username": Config.UKG_USERNAME,
        "ukg_password": Config.UKG_PASSWORD,
        "ukg_user_api_key": Config.UKG_USER_API_KEY,
        "cucm_host": Config.CUCM_HOST,
        "cucm_username": Config.CUCM_USERNAME,
        "cucm_password": Config.CUCM_PASSWORD,
        "cucm_version": Config.CUCM_VERSION,
        "cti_route_point_dn": Config.CTI_ROUTE_POINT_DN,
        "cti_device_name": Config.CTI_DEVICE_NAME,
        "sso_enabled": str(Config.SSO_ENABLED).lower(),
        "sso_provider_name": Config.SSO_PROVIDER_NAME,
        "sso_client_id": Config.SSO_CLIENT_ID,
        "sso_client_secret": Config.SSO_CLIENT_SECRET,
        "sso_discovery_url": Config.SSO_DISCOVERY_URL,
        "sso_authorization_endpoint": Config.SSO_AUTHORIZATION_ENDPOINT,
        "sso_token_endpoint": Config.SSO_TOKEN_ENDPOINT,
        "sso_userinfo_endpoint": Config.SSO_USERINFO_ENDPOINT,
        "sso_scopes": Config.SSO_SCOPES,
        "sso_allowed_domains": Config.SSO_ALLOWED_DOMAINS,
        "sso_allowed_emails": Config.SSO_ALLOWED_EMAILS,
        "sso_admin_role_claim": Config.SSO_ADMIN_ROLE_CLAIM,
    }
    result = {}
    for key, default in keys_defaults.items():
        result[key] = _get_config_value(session, key, default)
    return result


def _apply_ukg_config(session):
    """Re-configure the live UKG client from saved database settings."""
    from config import Config
    ukg = current_app.config["UKG_CLIENT"]
    ukg.base_url = _get_config_value(session, "ukg_base_url", Config.UKG_BASE_URL).rstrip("/")
    ukg.api_key = _get_config_value(session, "ukg_api_key", Config.UKG_API_KEY)
    ukg.client_id = _get_config_value(session, "ukg_client_id", Config.UKG_CLIENT_ID)
    ukg.client_secret = _get_config_value(session, "ukg_client_secret", Config.UKG_CLIENT_SECRET)
    ukg.username = _get_config_value(session, "ukg_username", Config.UKG_USERNAME)
    ukg.password = _get_config_value(session, "ukg_password", Config.UKG_PASSWORD)
    ukg.user_api_key = _get_config_value(session, "ukg_user_api_key", Config.UKG_USER_API_KEY)
    # Force re-authentication on next request
    ukg._access_token = None
    ukg._token_expires = None


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@admin_bp.route("/")
def dashboard():
    from models.database import Employee, TimePunch
    session = current_app.config["DB_SESSION_FACTORY"]()
    try:
        today = datetime.date.today()
        today_start = datetime.datetime.combine(today, datetime.time.min)

        total_employees = session.query(Employee).count()
        today_punches = (
            session.query(TimePunch)
            .filter(TimePunch.punch_time >= today_start)
            .count()
        )
        pending_syncs = (
            session.query(TimePunch)
            .filter(TimePunch.ukg_synced == "pending")
            .count()
        )
        failed_syncs = (
            session.query(TimePunch)
            .filter(TimePunch.ukg_synced == "failed")
            .count()
        )
        recent_punches = (
            session.query(TimePunch)
            .filter(TimePunch.punch_time >= today_start)
            .order_by(TimePunch.punch_time.desc())
            .limit(20)
            .all()
        )

        # Connection status checks
        cfg = _load_all_config(session)
        ukg_status = "connected" if cfg.get("ukg_base_url") else "not configured"
        cucm_status = "configured" if cfg.get("cucm_host") and cfg["cucm_host"] != "cucm.example.com" else "not configured"

        retry_worker = current_app.config.get("RETRY_WORKER")
        retry_stats = retry_worker.get_stats() if retry_worker else {
            "running": False, "last_run": None,
            "total_retried": 0, "total_succeeded": 0, "total_exhausted": 0,
        }

        return render_template(
            "dashboard.html",
            total_employees=total_employees,
            today_punches=today_punches,
            pending_syncs=pending_syncs,
            failed_syncs=failed_syncs,
            recent_punches=recent_punches,
            ukg_status=ukg_status,
            cucm_status=cucm_status,
            retry_stats=retry_stats,
        )
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@admin_bp.route("/config")
def config_page():
    db = current_app.config["DB_SESSION_FACTORY"]()
    try:
        config = _load_all_config(db)
        callback_url = url_for("auth.callback", _external=True)
        return render_template("config.html", config=config, callback_url=callback_url)
    finally:
        db.close()


@admin_bp.route("/config/save", methods=["POST"])
def save_config():
    session = current_app.config["DB_SESSION_FACTORY"]()
    try:
        config_keys = [
            "ukg_base_url", "ukg_api_key", "ukg_client_id", "ukg_client_secret",
            "ukg_username", "ukg_password", "ukg_user_api_key",
            "cucm_host", "cucm_username", "cucm_password", "cucm_version",
            "cti_route_point_dn", "cti_device_name",
            "sso_enabled", "sso_provider_name", "sso_client_id", "sso_client_secret",
            "sso_discovery_url", "sso_authorization_endpoint", "sso_token_endpoint",
            "sso_userinfo_endpoint", "sso_scopes", "sso_allowed_domains",
            "sso_allowed_emails", "sso_admin_role_claim",
        ]
        for key in config_keys:
            value = request.form.get(key, "")
            _set_config_value(session, key, value)

        session.commit()

        # Apply new UKG settings to the live client
        _apply_ukg_config(session)

        flash("Configuration saved successfully.", "success")
        logger.info("Configuration updated via admin portal")
    except Exception as e:
        session.rollback()
        flash(f"Error saving configuration: {e}", "danger")
        logger.exception("Error saving configuration")
    finally:
        session.close()

    return redirect(url_for("admin.config_page"))


@admin_bp.route("/config/test-ukg", methods=["POST"])
def test_ukg_connection():
    """Test the current UKG API connection."""
    ukg = current_app.config["UKG_CLIENT"]
    try:
        ukg._authenticate()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@admin_bp.route("/config/test-cucm", methods=["POST"])
def test_cucm_connection():
    """Test the current CUCM AXL connection."""
    from cisco.axl_client import AXLClient
    session = current_app.config["DB_SESSION_FACTORY"]()
    try:
        cfg = _load_all_config(session)
        axl = AXLClient(
            host=cfg["cucm_host"],
            username=cfg["cucm_username"],
            password=cfg["cucm_password"],
            version=cfg["cucm_version"],
        )
        axl.get_cti_route_point(cfg["cti_device_name"])
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Employees
# ---------------------------------------------------------------------------

@admin_bp.route("/employees")
def employees_page():
    from models.database import Employee
    session = current_app.config["DB_SESSION_FACTORY"]()
    try:
        employees = session.query(Employee).order_by(Employee.name).all()
        return render_template("employees.html", employees=employees)
    finally:
        session.close()


@admin_bp.route("/employees/add", methods=["POST"])
def add_employee():
    from models.database import Employee
    session = current_app.config["DB_SESSION_FACTORY"]()
    try:
        emp = Employee(
            employee_id=request.form["employee_id"],
            name=request.form["name"],
            phone_extension=request.form.get("phone_extension") or None,
            caller_id=request.form.get("caller_id") or None,
            ukg_employee_id=request.form["ukg_employee_id"],
        )
        session.add(emp)
        session.commit()
        flash(f"Employee {emp.name} added.", "success")
    except Exception as e:
        session.rollback()
        flash(f"Error adding employee: {e}", "danger")
    finally:
        session.close()
    return redirect(url_for("admin.employees_page"))


@admin_bp.route("/employees/update", methods=["POST"])
def update_employee():
    from models.database import Employee
    session = current_app.config["DB_SESSION_FACTORY"]()
    try:
        emp = (
            session.query(Employee)
            .filter_by(employee_id=request.form["employee_id"])
            .first()
        )
        if not emp:
            flash("Employee not found.", "danger")
            return redirect(url_for("admin.employees_page"))

        emp.name = request.form["name"]
        emp.phone_extension = request.form.get("phone_extension") or None
        emp.caller_id = request.form.get("caller_id") or None
        emp.ukg_employee_id = request.form["ukg_employee_id"]
        session.commit()
        flash(f"Employee {emp.name} updated.", "success")
    except Exception as e:
        session.rollback()
        flash(f"Error updating employee: {e}", "danger")
    finally:
        session.close()
    return redirect(url_for("admin.employees_page"))


@admin_bp.route("/employees/<employee_id>/delete", methods=["POST"])
def delete_employee(employee_id):
    from models.database import Employee
    session = current_app.config["DB_SESSION_FACTORY"]()
    try:
        emp = session.query(Employee).filter_by(employee_id=employee_id).first()
        if emp:
            session.delete(emp)
            session.commit()
            flash(f"Employee {employee_id} removed.", "success")
        else:
            flash("Employee not found.", "danger")
    finally:
        session.close()
    return redirect(url_for("admin.employees_page"))


# ---------------------------------------------------------------------------
# Punches
# ---------------------------------------------------------------------------

@admin_bp.route("/punches")
def punches_page():
    from models.database import TimePunch, Employee
    session = current_app.config["DB_SESSION_FACTORY"]()
    try:
        date_str = request.args.get("date", datetime.date.today().isoformat())
        selected_date = date_str
        date = datetime.date.fromisoformat(date_str)

        query = session.query(TimePunch).filter(
            TimePunch.punch_time >= datetime.datetime.combine(date, datetime.time.min),
            TimePunch.punch_time <= datetime.datetime.combine(date, datetime.time.max),
        )

        selected_status = request.args.get("status", "")
        if selected_status:
            query = query.filter(TimePunch.ukg_synced == selected_status)

        selected_employee = request.args.get("employee_id", "")
        if selected_employee:
            query = query.filter(TimePunch.employee_id == selected_employee)

        punches = query.order_by(TimePunch.punch_time.desc()).all()
        employees = session.query(Employee).order_by(Employee.name).all()

        return render_template(
            "punches.html",
            punches=punches,
            employees=employees,
            selected_date=selected_date,
            selected_status=selected_status,
            selected_employee=selected_employee,
        )
    finally:
        session.close()


@admin_bp.route("/punches/add", methods=["POST"])
def add_manual_punch():
    from models.database import TimePunch, Employee
    session = current_app.config["DB_SESSION_FACTORY"]()
    try:
        employee_id = request.form["employee_id"]
        punch_type = request.form["punch_type"]
        punch_time = datetime.datetime.fromisoformat(request.form["punch_time"])
        sync_to_ukg = "sync_to_ukg" in request.form

        punch = TimePunch(
            employee_id=employee_id,
            punch_type=punch_type,
            punch_time=punch_time,
            source_caller_id=None,
            ukg_synced="pending",
        )
        session.add(punch)
        session.commit()

        if sync_to_ukg:
            employee = session.query(Employee).filter_by(employee_id=employee_id).first()
            if employee:
                ukg = current_app.config["UKG_CLIENT"]
                try:
                    ukg.submit_time_punch(
                        employee_id=employee.ukg_employee_id,
                        punch_type=punch_type,
                        punch_time=punch_time,
                    )
                    punch.ukg_synced = "success"
                    session.commit()
                except Exception as e:
                    punch.ukg_synced = "failed"
                    punch.ukg_response = str(e)[:500]
                    session.commit()
                    flash(f"Punch recorded locally but UKG sync failed: {e}", "warning")
                    return redirect(url_for("admin.punches_page"))

        flash("Manual punch recorded.", "success")
    except Exception as e:
        session.rollback()
        flash(f"Error recording punch: {e}", "danger")
    finally:
        session.close()
    return redirect(url_for("admin.punches_page"))


@admin_bp.route("/punches/update", methods=["POST"])
def update_punch():
    from models.database import TimePunch, Employee
    session = current_app.config["DB_SESSION_FACTORY"]()
    try:
        punch = session.get(TimePunch,int(request.form["punch_id"]))
        if not punch:
            flash("Punch not found.", "danger")
            return redirect(url_for("admin.punches_page"))

        punch.punch_type = request.form["punch_type"]
        punch.punch_time = datetime.datetime.fromisoformat(request.form["punch_time"])

        resync = "resync_ukg" in request.form
        if resync:
            employee = session.query(Employee).filter_by(employee_id=punch.employee_id).first()
            if employee:
                ukg = current_app.config["UKG_CLIENT"]
                try:
                    ukg.submit_time_punch(
                        employee_id=employee.ukg_employee_id,
                        punch_type=punch.punch_type,
                        punch_time=punch.punch_time,
                    )
                    punch.ukg_synced = "success"
                    punch.ukg_response = None
                except Exception as e:
                    punch.ukg_synced = "failed"
                    punch.ukg_response = str(e)[:500]
                    flash(f"Punch updated but UKG re-sync failed: {e}", "warning")
        else:
            punch.ukg_synced = "pending"

        session.commit()
        flash("Punch updated.", "success")
    except Exception as e:
        session.rollback()
        flash(f"Error updating punch: {e}", "danger")
    finally:
        session.close()
    return redirect(url_for("admin.punches_page"))


@admin_bp.route("/punches/<int:punch_id>/delete", methods=["POST"])
def delete_punch(punch_id):
    from models.database import TimePunch
    session = current_app.config["DB_SESSION_FACTORY"]()
    try:
        punch = session.get(TimePunch,punch_id)
        if punch:
            session.delete(punch)
            session.commit()
            flash("Punch deleted.", "success")
        else:
            flash("Punch not found.", "danger")
    finally:
        session.close()
    return redirect(url_for("admin.punches_page"))


@admin_bp.route("/punches/retry", methods=["POST"])
def retry_failed():
    from models.database import TimePunch, Employee
    session = current_app.config["DB_SESSION_FACTORY"]()
    ukg = current_app.config["UKG_CLIENT"]
    try:
        date_str = request.form.get("date", datetime.date.today().isoformat())
        date = datetime.date.fromisoformat(date_str)

        failed = (
            session.query(TimePunch)
            .filter(
                TimePunch.ukg_synced.in_(["failed", "pending"]),
                TimePunch.punch_time >= datetime.datetime.combine(date, datetime.time.min),
                TimePunch.punch_time <= datetime.datetime.combine(date, datetime.time.max),
            )
            .all()
        )

        succeeded = 0
        errors = 0
        for punch in failed:
            employee = session.query(Employee).filter_by(employee_id=punch.employee_id).first()
            if not employee:
                continue
            try:
                ukg.submit_time_punch(
                    employee_id=employee.ukg_employee_id,
                    punch_type=punch.punch_type,
                    punch_time=punch.punch_time,
                )
                punch.ukg_synced = "success"
                punch.ukg_response = None
                punch.last_retry_at = datetime.datetime.utcnow()
                session.commit()
                succeeded += 1
            except Exception as e:
                punch.retry_count = (punch.retry_count or 0) + 1
                punch.ukg_response = str(e)[:500]
                punch.last_retry_at = datetime.datetime.utcnow()
                session.commit()
                errors += 1

        flash(f"Retry complete: {succeeded} succeeded, {errors} failed out of {len(failed)} total.", "success" if errors == 0 else "warning")
    except Exception as e:
        flash(f"Retry error: {e}", "danger")
    finally:
        session.close()
    return redirect(url_for("admin.punches_page", date=date_str))
