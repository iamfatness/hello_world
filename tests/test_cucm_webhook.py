"""Integration tests for CUCM webhook and IVR XML responses.

Validates that every XML document returned to Cisco IP phones is well-formed
and contains the exact elements the phone firmware expects to render.

Cisco IP Phone XML types exercised here:
  CiscoIPPhoneMenu   - top-level menu with MenuItem children
  CiscoIPPhoneInput  - single-field data entry screen
  CiscoIPPhoneText   - read-only text/confirmation screen
"""

import pytest
from lxml import etree

from app import create_app
from models.database import Employee, TimePunch


class TestConfig:
    SECRET_KEY = "test-secret"
    HOST = "localhost"
    PORT = 5000
    DEBUG = False
    CUCM_HOST = "test-cucm"
    CUCM_USERNAME = "admin"
    CUCM_PASSWORD = "password"
    CUCM_VERSION = "14.0"
    CUCM_VERIFY_SSL = False
    CTI_ROUTE_POINT_DN = "5000"
    CTI_DEVICE_NAME = "TestRoutePoint"
    UKG_BASE_URL = "https://test-ukg.example.com"
    UKG_API_KEY = "test-key"
    UKG_CLIENT_ID = "test-client"
    UKG_CLIENT_SECRET = "test-secret"
    UKG_USERNAME = "test-user"
    UKG_PASSWORD = "test-pass"
    UKG_USER_API_KEY = "test-user-key"
    DATABASE_URL = "sqlite:///:memory:"
    LOG_LEVEL = "DEBUG"


@pytest.fixture
def app():
    application = create_app(config=TestConfig)
    application.config["TESTING"] = True
    application.config["WTF_CSRF_ENABLED"] = False

    db = application.config["DB_SESSION_FACTORY"]()
    db.add(Employee(
        employee_id="E100",
        name="Alice Smith",
        phone_extension="2001",
        caller_id="5551110001",
        ukg_employee_id="UKG100",
    ))
    db.commit()
    db.close()

    yield application

    worker = application.config.get("RETRY_WORKER")
    if worker:
        worker.stop()


@pytest.fixture
def client(app):
    return app.test_client()


def _parse_xml(data):
    """Parse response bytes and return the root Element."""
    return etree.fromstring(data)


# ---------------------------------------------------------------------------
# /webhook/call - POST with CUCM call data
# ---------------------------------------------------------------------------

class TestCUCMWebhookCall:
    def test_post_known_caller_returns_menu(self, client):
        resp = client.post("/webhook/call", data={
            "callerid": "5551110001",
            "callednumber": "5000",
            "devicename": "SEP001122334455",
        })
        assert resp.status_code == 200
        assert resp.content_type.startswith("text/xml")
        xml = _parse_xml(resp.data)
        assert xml.tag == "CiscoIPPhoneMenu"

    def test_post_unknown_caller_returns_input(self, client):
        resp = client.post("/webhook/call", data={
            "callerid": "9998887777",
            "callednumber": "5000",
            "devicename": "SEP001122334455",
        })
        assert resp.status_code == 200
        xml = _parse_xml(resp.data)
        assert xml.tag == "CiscoIPPhoneInput"

    def test_get_request_also_accepted(self, client):
        resp = client.get("/webhook/call?callerid=5551110001&callednumber=5000")
        assert resp.status_code == 200
        xml = _parse_xml(resp.data)
        assert xml.tag == "CiscoIPPhoneMenu"

    def test_missing_callerid_returns_input(self, client):
        resp = client.post("/webhook/call", data={"callednumber": "5000"})
        assert resp.status_code == 200
        xml = _parse_xml(resp.data)
        assert xml.tag == "CiscoIPPhoneInput"

    def test_empty_callerid_returns_input(self, client):
        resp = client.post("/webhook/call", data={"callerid": "", "callednumber": "5000"})
        assert resp.status_code == 200
        xml = _parse_xml(resp.data)
        assert xml.tag == "CiscoIPPhoneInput"


# ---------------------------------------------------------------------------
# CiscoIPPhoneMenu structure validation
# ---------------------------------------------------------------------------

class TestMenuXMLStructure:
    def test_menu_has_title(self, client):
        xml = _parse_xml(client.get("/ivr/menu").data)
        assert xml.tag == "CiscoIPPhoneMenu"
        assert xml.find("Title") is not None
        assert xml.find("Title").text

    def test_menu_has_prompt(self, client):
        xml = _parse_xml(client.get("/ivr/menu").data)
        assert xml.find("Prompt") is not None

    def test_menu_has_three_items(self, client):
        xml = _parse_xml(client.get("/ivr/menu").data)
        items = xml.findall("MenuItem")
        assert len(items) == 3

    def test_menu_items_have_name_and_url(self, client):
        xml = _parse_xml(client.get("/ivr/menu").data)
        for item in xml.findall("MenuItem"):
            assert item.find("Name") is not None
            assert item.find("URL") is not None
            assert item.find("URL").text.startswith("http")

    def test_menu_item_urls_point_to_ivr(self, client):
        xml = _parse_xml(client.get("/ivr/menu").data)
        urls = [item.find("URL").text for item in xml.findall("MenuItem")]
        assert any("/ivr/punch?type=clock_in" in u for u in urls)
        assert any("/ivr/punch?type=clock_out" in u for u in urls)
        assert any("/ivr/status" in u for u in urls)

    def test_menu_items_have_distinct_names(self, client):
        xml = _parse_xml(client.get("/ivr/menu").data)
        names = [item.find("Name").text for item in xml.findall("MenuItem")]
        assert len(names) == len(set(names))

    def test_xml_declaration_present(self, client):
        raw = client.get("/ivr/menu").data
        assert raw.startswith(b"<?xml")

    def test_content_type_is_text_xml(self, client):
        resp = client.get("/ivr/menu")
        assert resp.content_type.startswith("text/xml")


# ---------------------------------------------------------------------------
# CiscoIPPhoneInput structure validation
# ---------------------------------------------------------------------------

class TestInputXMLStructure:
    def _get_input_xml(self, client):
        return _parse_xml(client.get("/ivr/punch?type=clock_in").data)

    def test_input_tag(self, client):
        assert self._get_input_xml(client).tag == "CiscoIPPhoneInput"

    def test_input_has_title(self, client):
        xml = self._get_input_xml(client)
        assert xml.find("Title") is not None
        assert xml.find("Title").text

    def test_input_has_prompt(self, client):
        xml = self._get_input_xml(client)
        assert xml.find("Prompt") is not None

    def test_input_has_url(self, client):
        xml = self._get_input_xml(client)
        assert xml.find("URL") is not None
        assert "/ivr/authenticate" in xml.find("URL").text

    def test_input_has_input_item(self, client):
        xml = self._get_input_xml(client)
        item = xml.find("InputItem")
        assert item is not None

    def test_input_item_has_required_children(self, client):
        xml = self._get_input_xml(client)
        item = xml.find("InputItem")
        assert item.find("DisplayName") is not None
        assert item.find("QueryStringParam") is not None
        assert item.find("InputFlags") is not None

    def test_input_flags_is_numeric(self, client):
        xml = self._get_input_xml(client)
        flags = xml.find("InputItem/InputFlags").text
        assert flags == "N"

    def test_query_param_is_employee_id(self, client):
        xml = self._get_input_xml(client)
        param = xml.find("InputItem/QueryStringParam").text
        assert param == "employee_id"

    def test_clock_out_url_contains_type(self, client):
        xml = _parse_xml(client.get("/ivr/punch?type=clock_out").data)
        assert xml.tag == "CiscoIPPhoneInput"
        url = xml.find("URL").text
        assert "type=clock_out" in url


# ---------------------------------------------------------------------------
# CiscoIPPhoneText structure validation
# ---------------------------------------------------------------------------

class TestTextXMLStructure:
    def _get_text_xml(self, client):
        return _parse_xml(
            client.get("/ivr/authenticate?type=clock_in&employee_id=E100").data
        )

    def test_text_tag(self, client):
        assert self._get_text_xml(client).tag == "CiscoIPPhoneText"

    def test_text_has_title(self, client):
        xml = self._get_text_xml(client)
        assert xml.find("Title") is not None
        assert xml.find("Title").text == "Success"

    def test_text_has_body(self, client):
        xml = self._get_text_xml(client)
        assert xml.find("Text") is not None
        assert xml.find("Text").text

    def test_error_screen_for_unknown_employee(self, client):
        xml = _parse_xml(
            client.get("/ivr/authenticate?type=clock_in&employee_id=ZZZZZ").data
        )
        assert xml.tag == "CiscoIPPhoneText"
        assert xml.find("Title").text == "Error"
        assert "not found" in xml.find("Text").text.lower()

    def test_error_screen_for_empty_employee_id(self, client):
        xml = _parse_xml(
            client.get("/ivr/authenticate?type=clock_in&employee_id=").data
        )
        assert xml.tag == "CiscoIPPhoneText"
        assert xml.find("Title").text == "Error"


# ---------------------------------------------------------------------------
# Input validation rejection tests
# ---------------------------------------------------------------------------

class TestIVRInputValidation:
    def test_employee_id_with_special_chars_rejected(self, client):
        xml = _parse_xml(
            client.get("/ivr/authenticate?type=clock_in&employee_id=E%3BDROPTABLE").data
        )
        assert xml.tag == "CiscoIPPhoneText"
        assert xml.find("Title").text == "Error"

    def test_employee_id_too_long_rejected(self, client):
        long_id = "A" * 21
        xml = _parse_xml(
            client.get(f"/ivr/authenticate?type=clock_in&employee_id={long_id}").data
        )
        assert xml.tag == "CiscoIPPhoneText"
        assert xml.find("Title").text == "Error"

    def test_invalid_punch_type_rejected(self, client):
        xml = _parse_xml(
            client.get("/ivr/authenticate?type=invalid_type&employee_id=E100").data
        )
        assert xml.tag == "CiscoIPPhoneText"
        assert xml.find("Title").text == "Error"

    def test_pin_non_numeric_rejected(self, client, app):
        app.config["REQUIRE_EMPLOYEE_PIN"] = True
        xml = _parse_xml(
            client.get("/ivr/verify-pin?employee_id=E100&type=clock_in&pin=abc1").data
        )
        assert xml.tag == "CiscoIPPhoneText"
        assert xml.find("Title").text == "Error"
        app.config["REQUIRE_EMPLOYEE_PIN"] = False

    def test_pin_too_short_rejected(self, client, app):
        app.config["REQUIRE_EMPLOYEE_PIN"] = True
        xml = _parse_xml(
            client.get("/ivr/verify-pin?employee_id=E100&type=clock_in&pin=123").data
        )
        assert xml.tag == "CiscoIPPhoneText"
        assert xml.find("Title").text == "Error"
        app.config["REQUIRE_EMPLOYEE_PIN"] = False

    def test_valid_employee_id_accepted(self, client):
        resp = client.get("/ivr/authenticate?type=clock_in&employee_id=E100")
        assert resp.status_code == 200
        xml = _parse_xml(resp.data)
        assert xml.tag == "CiscoIPPhoneText"
        assert xml.find("Title").text == "Success"


# ---------------------------------------------------------------------------
# Webhook /webhook/call with POST body (as CUCM actually sends it)
# ---------------------------------------------------------------------------

class TestCUCMWebhookPostBody:
    def test_known_caller_menu_has_correct_items(self, client):
        resp = client.post("/webhook/call", data={
            "callerid": "5551110001",
            "callednumber": "5000",
        })
        xml = _parse_xml(resp.data)
        assert xml.tag == "CiscoIPPhoneMenu"
        items = xml.findall("MenuItem")
        names = [i.find("Name").text for i in items]
        assert "Clock In" in names
        assert "Clock Out" in names

    def test_extra_cucm_fields_ignored(self, client):
        resp = client.post("/webhook/call", data={
            "callerid": "5551110001",
            "callednumber": "5000",
            "devicename": "SEP112233445566",
            "partition": "Internal_PT",
            "calltype": "InboundCall",
        })
        assert resp.status_code == 200
        xml = _parse_xml(resp.data)
        assert xml.tag in ("CiscoIPPhoneMenu", "CiscoIPPhoneInput")

    def test_response_is_valid_xml(self, client):
        resp = client.post("/webhook/call", data={"callerid": "5551110001"})
        assert resp.status_code == 200
        root = etree.fromstring(resp.data)
        assert root is not None
