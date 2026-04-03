"""Cisco CUCM CTI Route Point handler.

In a Cisco CUCM environment, a CTI Route Point is a virtual device that
can receive calls and trigger application logic. This module handles:

1. Receiving call events from CUCM (via HTTP triggers / CURRI)
2. Looking up the caller by their Caller ID (ANI)
3. Directing the call flow to the appropriate IVR XML service

CUCM Configuration Required:
- Create a CTI Route Point device in CUCM admin
- Assign a Directory Number (DN) to the route point
- Configure an Application User with CTI permissions
- Set up HTTP trigger to forward call events to this app's /webhook/call endpoint
"""

import logging

logger = logging.getLogger(__name__)


class CTIHandler:
    """Processes incoming call events from the Cisco CTI Route Point."""

    def __init__(self, db_session_factory):
        self.db_session_factory = db_session_factory

    def handle_incoming_call(self, caller_id, called_number):
        """Process an incoming call event from CUCM.

        Args:
            caller_id: The caller's phone number (ANI).
            called_number: The dialed number (DNIS) - should match our route point.

        Returns:
            dict with call handling instructions.
        """
        logger.info(
            "Incoming call from %s to route point %s", caller_id, called_number
        )

        from models.database import Employee

        session = self.db_session_factory()
        try:
            employee = (
                session.query(Employee)
                .filter(Employee.caller_id == caller_id)
                .first()
            )

            if employee:
                logger.info(
                    "Recognized employee: %s (ID: %s)",
                    employee.name, employee.employee_id
                )
                return {
                    "action": "serve_menu",
                    "employee_id": employee.employee_id,
                    "employee_name": employee.name,
                    "recognized": True,
                }

            logger.info("Unknown caller %s - will prompt for employee ID", caller_id)
            return {
                "action": "prompt_employee_id",
                "recognized": False,
            }
        finally:
            session.close()

    def lookup_employee_by_id(self, employee_id):
        """Look up an employee by their manually-entered ID.

        Args:
            employee_id: The employee ID entered via phone keypad.

        Returns:
            Employee record or None.
        """
        from models.database import Employee

        session = self.db_session_factory()
        try:
            return (
                session.query(Employee)
                .filter(Employee.employee_id == employee_id)
                .first()
            )
        finally:
            session.close()
