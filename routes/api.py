"""Admin REST API for managing employees and reviewing punch records.

These endpoints are for administrative use - managing the employee roster,
reviewing punch history, and retrying failed UKG syncs.
"""

import datetime
import logging
from flask import Blueprint, request, jsonify, current_app

from auth.api_keys import machine_auth_required

logger = logging.getLogger(__name__)
api_bp = Blueprint("api", __name__, url_prefix="/api")


@api_bp.before_request
def _require_machine_auth():
    """Require API key (or SSO session) for all /api endpoints."""
    return machine_auth_required()


@api_bp.route("/employees", methods=["GET"])
def list_employees():
    """List all registered employees."""
    from models.database import Employee

    session = current_app.config["DB_SESSION_FACTORY"]()
    try:
        employees = session.query(Employee).all()
        return jsonify([
            {
                "id": e.id,
                "employee_id": e.employee_id,
                "name": e.name,
                "phone_extension": e.phone_extension,
                "caller_id": e.caller_id,
                "ukg_employee_id": e.ukg_employee_id,
            }
            for e in employees
        ])
    finally:
        session.close()


@api_bp.route("/employees", methods=["POST"])
def add_employee():
    """Register a new employee.

    JSON body:
        employee_id: Unique employee identifier
        name: Employee full name
        phone_extension: Their desk phone extension (optional)
        caller_id: Their phone number for auto-identification (optional)
        ukg_employee_id: Their ID in the UKG system
    """
    from models.database import Employee

    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    required = ["employee_id", "name", "ukg_employee_id"]
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({"error": f"Missing required fields: {missing}"}), 400

    session = current_app.config["DB_SESSION_FACTORY"]()
    try:
        existing = (
            session.query(Employee)
            .filter(Employee.employee_id == data["employee_id"])
            .first()
        )
        if existing:
            return jsonify({"error": "Employee ID already exists"}), 409

        employee = Employee(
            employee_id=data["employee_id"],
            name=data["name"],
            phone_extension=data.get("phone_extension"),
            caller_id=data.get("caller_id"),
            ukg_employee_id=data["ukg_employee_id"],
        )
        session.add(employee)
        session.commit()

        logger.info("Employee registered: %s (%s)", data["name"], data["employee_id"])
        return jsonify({"message": "Employee registered", "id": employee.id}), 201
    except Exception as e:
        session.rollback()
        logger.exception("Error registering employee: %s", e)
        return jsonify({"error": "Failed to register employee"}), 500
    finally:
        session.close()


@api_bp.route("/employees/<employee_id>", methods=["DELETE"])
def remove_employee(employee_id):
    """Remove an employee from the system."""
    from models.database import Employee

    session = current_app.config["DB_SESSION_FACTORY"]()
    try:
        employee = (
            session.query(Employee)
            .filter(Employee.employee_id == employee_id)
            .first()
        )
        if not employee:
            return jsonify({"error": "Employee not found"}), 404

        session.delete(employee)
        session.commit()
        return jsonify({"message": f"Employee {employee_id} removed"})
    finally:
        session.close()


@api_bp.route("/punches", methods=["GET"])
def list_punches():
    """List time punches with optional filters.

    Query params:
        employee_id: Filter by employee
        date: Filter by date (YYYY-MM-DD), defaults to today
        status: Filter by UKG sync status (pending/success/failed)
    """
    from models.database import TimePunch

    session = current_app.config["DB_SESSION_FACTORY"]()
    try:
        query = session.query(TimePunch)

        employee_id = request.args.get("employee_id")
        if employee_id:
            query = query.filter(TimePunch.employee_id == employee_id)

        date_str = request.args.get("date")
        if date_str:
            date = datetime.date.fromisoformat(date_str)
        else:
            date = datetime.date.today()

        query = query.filter(
            TimePunch.punch_time >= datetime.datetime.combine(date, datetime.time.min),
            TimePunch.punch_time <= datetime.datetime.combine(date, datetime.time.max),
        )

        status = request.args.get("status")
        if status:
            query = query.filter(TimePunch.ukg_synced == status)

        punches = query.order_by(TimePunch.punch_time.desc()).all()
        return jsonify([
            {
                "id": p.id,
                "employee_id": p.employee_id,
                "punch_type": p.punch_type,
                "punch_time": p.punch_time.isoformat(),
                "source_caller_id": p.source_caller_id,
                "ukg_synced": p.ukg_synced,
                "ukg_response": p.ukg_response,
            }
            for p in punches
        ])
    finally:
        session.close()


@api_bp.route("/punches/retry", methods=["POST"])
def retry_failed_syncs():
    """Retry all failed UKG syncs for today's punches as a single batch call."""
    from models.database import TimePunch, Employee

    session = current_app.config["DB_SESSION_FACTORY"]()
    ukg_client = current_app.config["UKG_CLIENT"]

    try:
        today = datetime.date.today()
        failed = (
            session.query(TimePunch)
            .filter(
                TimePunch.ukg_synced == "failed",
                TimePunch.punch_time >= datetime.datetime.combine(
                    today, datetime.time.min
                ),
            )
            .all()
        )

        if not failed:
            return jsonify({"retried": 0, "results": []})

        # Load all employees in one query
        emp_ids = {p.employee_id for p in failed}
        employees = {
            e.employee_id: e
            for e in session.query(Employee)
            .filter(Employee.employee_id.in_(emp_ids))
            .all()
        }

        submittable = [(p, employees[p.employee_id]) for p in failed if p.employee_id in employees]
        skipped = [{"id": p.id, "status": "skipped", "reason": "employee not found"}
                   for p in failed if p.employee_id not in employees]

        results = list(skipped)

        if submittable:
            batch_payload = [
                {"employee_id": emp.ukg_employee_id,
                 "punch_type": punch.punch_type,
                 "punch_time": punch.punch_time}
                for punch, emp in submittable
            ]
            try:
                batch_results = ukg_client.submit_punch_batch(batch_payload)
                for (punch, _), result in zip(submittable, batch_results):
                    if result.get("status") == "accepted":
                        punch.ukg_synced = "success"
                        punch.ukg_response = None
                        results.append({"id": punch.id, "status": "success"})
                    else:
                        error = result.get("error", "rejected")
                        punch.ukg_response = str(error)[:500]
                        results.append({"id": punch.id, "status": "failed", "error": str(error)})
            except Exception as e:
                for punch, _ in submittable:
                    punch.ukg_response = str(e)[:500]
                    results.append({"id": punch.id, "status": "failed", "error": str(e)})
            session.commit()

        return jsonify({"retried": len(failed), "results": results})
    finally:
        session.close()
