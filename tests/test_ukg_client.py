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


def _batch_mock(results):
    """Build mock post side_effect for [auth_response, batch_response]."""
    auth_resp = MagicMock()
    auth_resp.json.return_value = {"access_token": "tok123", "expires_in": 3600}
    auth_resp.raise_for_status = MagicMock()

    batch_resp = MagicMock()
    batch_resp.json.return_value = {"results": results}
    batch_resp.raise_for_status = MagicMock()

    return [auth_resp, batch_resp]


@patch("ukg.api_client.requests.post")
def test_submit_time_punch(mock_post):
    mock_post.side_effect = _batch_mock([{"status": "accepted", "punchId": "punch-1"}])

    client = _make_client()
    result = client.submit_time_punch(
        employee_id="UKG001",
        punch_type="clock_in",
        punch_time=datetime.datetime(2026, 4, 3, 8, 0, 0),
    )

    assert result["status"] == "accepted"
    assert mock_post.call_count == 2

    # Verify batch payload contains the punch
    batch_call = mock_post.call_args_list[1]
    payload = batch_call[1]["json"]
    assert len(payload["punches"]) == 1
    assert payload["punches"][0]["employeeIdentifier"] == "UKG001"
    assert payload["punches"][0]["punchType"] == "IN"
    assert payload["punches"][0]["punchDateTime"] == "2026-04-03T08:00:00"


@patch("ukg.api_client.requests.post")
def test_submit_clock_out(mock_post):
    mock_post.side_effect = _batch_mock([{"status": "accepted", "punchId": "punch-2"}])

    client = _make_client()
    result = client.submit_time_punch(
        "UKG001", "clock_out",
        punch_time=datetime.datetime(2026, 4, 3, 17, 0, 0),
    )

    batch_payload = mock_post.call_args_list[1][1]["json"]
    assert batch_payload["punches"][0]["punchType"] == "OUT"
    assert result["status"] == "accepted"


@patch("ukg.api_client.requests.post")
def test_submit_punch_batch(mock_post):
    mock_post.side_effect = _batch_mock([
        {"status": "accepted", "punchId": "p1"},
        {"status": "accepted", "punchId": "p2"},
        {"status": "rejected", "error": "Employee not found"},
    ])

    client = _make_client()
    punches = [
        {"employee_id": "UKG001", "punch_type": "clock_in",
         "punch_time": datetime.datetime(2026, 4, 3, 8, 0, 0)},
        {"employee_id": "UKG002", "punch_type": "clock_out",
         "punch_time": datetime.datetime(2026, 4, 3, 17, 0, 0)},
        {"employee_id": "UKG999", "punch_type": "clock_in",
         "punch_time": datetime.datetime(2026, 4, 3, 8, 5, 0)},
    ]
    results = client.submit_punch_batch(punches)

    assert len(results) == 3
    assert results[0]["status"] == "accepted"
    assert results[1]["status"] == "accepted"
    assert results[2]["status"] == "rejected"
    assert "not found" in results[2]["error"]

    # Verify all three punches sent in one POST
    batch_payload = mock_post.call_args_list[1][1]["json"]
    assert len(batch_payload["punches"]) == 3
    assert batch_payload["punches"][0]["punchType"] == "IN"
    assert batch_payload["punches"][1]["punchType"] == "OUT"


@patch("ukg.api_client.requests.post")
def test_submit_punch_batch_empty(mock_post):
    client = _make_client()
    results = client.submit_punch_batch([])
    assert results == []
    mock_post.assert_not_called()


@patch("ukg.api_client.requests.post")
def test_submit_time_punch_rejected_raises(mock_post):
    mock_post.side_effect = _batch_mock([{"status": "rejected", "error": "Invalid employee"}])

    client = _make_client()
    import pytest
    with pytest.raises(RuntimeError, match="Invalid employee"):
        client.submit_time_punch(
            "UKG999", "clock_in",
            punch_time=datetime.datetime(2026, 4, 3, 8, 0, 0),
        )


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
