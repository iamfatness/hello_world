"""Tests for Cisco IP Phone XML Services generation."""

import datetime
from lxml import etree

from cisco.phone_services import (
    build_welcome_menu,
    build_employee_id_prompt,
    build_confirmation_screen,
    build_status_screen,
)


def _parse(xml_bytes):
    return etree.fromstring(xml_bytes)


def test_welcome_menu_structure():
    xml = _parse(build_welcome_menu("http://localhost:5000"))
    assert xml.tag == "CiscoIPPhoneMenu"
    assert xml.find("Title").text == "Time Clock"
    items = xml.findall("MenuItem")
    assert len(items) == 3
    assert items[0].find("Name").text == "Clock In"
    assert items[1].find("Name").text == "Clock Out"
    assert items[2].find("Name").text == "Check Status"


def test_welcome_menu_urls():
    xml = _parse(build_welcome_menu("http://myserver:5000"))
    items = xml.findall("MenuItem")
    assert "myserver:5000/ivr/punch?type=clock_in" in items[0].find("URL").text
    assert "myserver:5000/ivr/punch?type=clock_out" in items[1].find("URL").text
    assert "myserver:5000/ivr/status" in items[2].find("URL").text


def test_employee_id_prompt():
    xml = _parse(build_employee_id_prompt("http://localhost:5000", "clock_in"))
    assert xml.tag == "CiscoIPPhoneInput"
    assert xml.find("Title").text == "Employee ID"
    input_item = xml.find("InputItem")
    assert input_item.find("InputFlags").text == "N"
    assert "type=clock_in" in xml.find("URL").text


def test_confirmation_screen():
    xml = _parse(build_confirmation_screen("Success", "Clock In recorded"))
    assert xml.tag == "CiscoIPPhoneText"
    assert xml.find("Title").text == "Success"
    assert xml.find("Text").text == "Clock In recorded"


def test_status_screen_with_punch():
    xml = _parse(build_status_screen(
        "John Doe",
        "clock_in",
        datetime.datetime(2026, 4, 3, 8, 30),
    ))
    assert xml.tag == "CiscoIPPhoneText"
    text = xml.find("Text").text
    assert "John Doe" in text
    assert "Clocked In" in text
    assert "08:30 AM" in text


def test_status_screen_no_punches():
    xml = _parse(build_status_screen("Jane Smith", None, None))
    text = xml.find("Text").text
    assert "Jane Smith" in text
    assert "No punches recorded" in text
