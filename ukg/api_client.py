"""UKG Pro Workforce Management API client.

Handles authentication and time punch submission to the UKG (Ultimate Kronos
Group) Pro WFM platform, formerly known as Kronos Workforce Central.

UKG API Authentication Flow:
1. Obtain an access token via OAuth2 client credentials + user credentials
2. Use the token to call the Timekeeping API to submit punches

Reference: UKG Pro WFM Developer Hub
"""

import logging
import datetime
import requests

logger = logging.getLogger(__name__)


class UKGApiClient:
    """Client for UKG Pro Workforce Management REST API."""

    def __init__(self, base_url, api_key, client_id, client_secret,
                 username, password, user_api_key):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.client_id = client_id
        self.client_secret = client_secret
        self.username = username
        self.password = password
        self.user_api_key = user_api_key
        self._access_token = None
        self._token_expires = None

    def _authenticate(self):
        """Obtain an OAuth2 access token from UKG."""
        url = f"{self.base_url}/authentication/token"
        payload = {
            "grant_type": "password",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "username": self.username,
            "password": self.password,
        }
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Api-Key": self.api_key,
            "US-Customer-Api-Key": self.user_api_key,
        }

        logger.info("Authenticating with UKG API at %s", url)
        response = requests.post(url, data=payload, headers=headers, timeout=30)
        response.raise_for_status()

        data = response.json()
        self._access_token = data["access_token"]
        expires_in = data.get("expires_in", 3600)
        self._token_expires = (
            datetime.datetime.utcnow() + datetime.timedelta(seconds=expires_in - 60)
        )
        logger.info("UKG authentication successful, token expires in %ds", expires_in)

    def _get_headers(self):
        """Get authenticated request headers, refreshing token if needed."""
        if (
            self._access_token is None
            or self._token_expires is None
            or datetime.datetime.utcnow() >= self._token_expires
        ):
            self._authenticate()

        return {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
            "Api-Key": self.api_key,
            "US-Customer-Api-Key": self.user_api_key,
        }

    def submit_time_punch(self, employee_id, punch_type, punch_time):
        """Submit a single clock-in or clock-out punch to UKG.

        Args:
            employee_id: The UKG employee identifier.
            punch_type: Either 'clock_in' or 'clock_out'.
            punch_time: datetime of the punch (required — never defaults to now).

        Returns:
            dict with the API response data.

        Raises:
            requests.HTTPError: If the API call fails.
        """
        results = self.submit_punch_batch([{
            "employee_id": employee_id,
            "punch_type": punch_type,
            "punch_time": punch_time,
        }])
        result = results[0]
        if result.get("status") != "accepted":
            raise RuntimeError(f"UKG rejected punch: {result.get('error', 'unknown error')}")
        return result

    def submit_punch_batch(self, punches):
        """Submit multiple punches in a single API call to avoid concurrent requests.

        Args:
            punches: list of dicts, each with keys:
                       employee_id  - UKG employee identifier
                       punch_type   - 'clock_in' or 'clock_out'
                       punch_time   - datetime of the punch

        Returns:
            list of result dicts parallel to the input list, each containing:
              status - 'accepted' or 'rejected'
              punchId - on success
              error   - on rejection

        Raises:
            requests.HTTPError: If the batch API call itself fails.
        """
        if not punches:
            return []

        url = f"{self.base_url}/personnel/v1/employee-punches/batch"

        payload = {
            "punches": [
                {
                    "employeeIdentifier": p["employee_id"],
                    "punchType": "IN" if p["punch_type"] == "clock_in" else "OUT",
                    "punchDateTime": p["punch_time"].strftime("%Y-%m-%dT%H:%M:%S"),
                    "punchSource": "PHONE_SYSTEM",
                }
                for p in punches
            ]
        }

        logger.info("Submitting batch of %d punches to UKG", len(punches))

        response = requests.post(
            url, json=payload, headers=self._get_headers(), timeout=60
        )
        response.raise_for_status()

        data = response.json()
        results = data["results"]
        accepted = sum(1 for r in results if r.get("status") == "accepted")
        logger.info("UKG batch complete: %d/%d accepted", accepted, len(punches))
        return results

    def get_employee_punches(self, employee_id, date=None):
        """Retrieve an employee's punches for a given date.

        Args:
            employee_id: The UKG employee identifier.
            date: Date to query (defaults to today).

        Returns:
            list of punch records.
        """
        if date is None:
            date = datetime.date.today()

        url = f"{self.base_url}/personnel/v1/employee-punches"
        params = {
            "employeeIdentifier": employee_id,
            "startDate": date.strftime("%Y-%m-%d"),
            "endDate": date.strftime("%Y-%m-%d"),
        }

        response = requests.get(
            url, params=params, headers=self._get_headers(), timeout=30
        )
        response.raise_for_status()
        return response.json()

    def validate_employee(self, employee_id):
        """Verify that an employee exists in UKG.

        Args:
            employee_id: The UKG employee identifier.

        Returns:
            Employee data dict or None if not found.
        """
        url = f"{self.base_url}/personnel/v1/employees/{employee_id}"

        try:
            response = requests.get(
                url, headers=self._get_headers(), timeout=30
            )
            response.raise_for_status()
            return response.json()
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                return None
            raise
