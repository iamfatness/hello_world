"""Tests for UKG API client."""

import datetime
from unittest.mock import patch, MagicMock

from ukg.api_client import UKGApiClient


def _make_client():
    return UKGApiClient(
        base_url="https://test.ultipro.com",
        api_key="key",
        client_id="client",
        client_secret="secret",
        username="user",
        password="pass",
        user_api_key="ukey",
    )


@patch("ukg.api_client.requests.post")
def test_authenticate(mock_post):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"access_token": "tok123", "expires_in": 3600}
    mock_resp.raise_for_status = MagicMock()
    mock_post.return_value = mock_resp

    client = _make_client()
    client._authenticate()

    assert client._access_token == "tok123"
    mock_post.assert_called_once()
    call_url = mock_post.call_args[0][0]
    assert "/authentication/token" in call_url


@patch("ukg.api_client.requests.post")
def test_submit_time_punch(mock_post):
    # First call is auth, second is the punch
    auth_resp = MagicMock()
    auth_resp.json.return_value = {"access_token": "tok123", "expires_in": 3600}
    auth_resp.raise_for_status = MagicMock()

    punch_resp = MagicMock()
    punch_resp.json.return_value = {"id": "punch-1", "status": "accepted"}
    punch_resp.raise_for_status = MagicMock()

    mock_post.side_effect = [auth_resp, punch_resp]

    client = _make_client()
    result = client.submit_time_punch(
        employee_id="UKG001",
        punch_type="clock_in",
        punch_time=datetime.datetime(2026, 4, 3, 8, 0, 0),
    )

    assert result["status"] == "accepted"
    assert mock_post.call_count == 2

    # Verify punch payload
    punch_call = mock_post.call_args_list[1]
    payload = punch_call[1]["json"]
    assert payload["employeeIdentifier"] == "UKG001"
    assert payload["punchType"] == "IN"


@patch("ukg.api_client.requests.post")
def test_submit_clock_out(mock_post):
    auth_resp = MagicMock()
    auth_resp.json.return_value = {"access_token": "tok123", "expires_in": 3600}
    auth_resp.raise_for_status = MagicMock()

    punch_resp = MagicMock()
    punch_resp.json.return_value = {"id": "punch-2", "status": "accepted"}
    punch_resp.raise_for_status = MagicMock()

    mock_post.side_effect = [auth_resp, punch_resp]

    client = _make_client()
    result = client.submit_time_punch("UKG001", "clock_out")

    payload = mock_post.call_args_list[1][1]["json"]
    assert payload["punchType"] == "OUT"


@patch("ukg.api_client.requests.get")
@patch("ukg.api_client.requests.post")
def test_get_employee_punches(mock_post, mock_get):
    auth_resp = MagicMock()
    auth_resp.json.return_value = {"access_token": "tok123", "expires_in": 3600}
    auth_resp.raise_for_status = MagicMock()
    mock_post.return_value = auth_resp

    get_resp = MagicMock()
    get_resp.json.return_value = [{"punchType": "IN", "punchDateTime": "2026-04-03T08:00:00"}]
    get_resp.raise_for_status = MagicMock()
    mock_get.return_value = get_resp

    client = _make_client()
    punches = client.get_employee_punches("UKG001", date=datetime.date(2026, 4, 3))

    assert len(punches) == 1
    assert punches[0]["punchType"] == "IN"


@patch("ukg.api_client.requests.get")
@patch("ukg.api_client.requests.post")
def test_validate_employee_found(mock_post, mock_get):
    auth_resp = MagicMock()
    auth_resp.json.return_value = {"access_token": "tok123", "expires_in": 3600}
    auth_resp.raise_for_status = MagicMock()
    mock_post.return_value = auth_resp

    get_resp = MagicMock()
    get_resp.json.return_value = {"id": "UKG001", "name": "Test User"}
    get_resp.raise_for_status = MagicMock()
    mock_get.return_value = get_resp

    client = _make_client()
    result = client.validate_employee("UKG001")
    assert result["id"] == "UKG001"
