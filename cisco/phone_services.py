"""Cisco IP Phone XML Services generator.

Cisco IP phones can render XML-based menus, input forms, and text screens.
This module generates the XML payloads that drive the IVR-like experience
on the phone's display when an employee calls the clock-in route point.

Reference: Cisco Unified IP Phone Services Application Development Notes
"""

from lxml import etree


def build_welcome_menu(app_url):
    """Main menu shown when an employee calls the clock-in line.

    Presents options:
      1 - Clock In
      2 - Clock Out
      3 - Check Status
    """
    root = etree.Element("CiscoIPPhoneMenu")
    etree.SubElement(root, "Title").text = "Time Clock"
    etree.SubElement(root, "Prompt").text = "Select an option"

    for key, label, action in [
        ("1", "Clock In", f"{app_url}/ivr/punch?type=clock_in"),
        ("2", "Clock Out", f"{app_url}/ivr/punch?type=clock_out"),
        ("3", "Check Status", f"{app_url}/ivr/status"),
    ]:
        item = etree.SubElement(root, "MenuItem")
        etree.SubElement(item, "Name").text = label
        etree.SubElement(item, "URL").text = action

    return etree.tostring(root, xml_declaration=True, encoding="UTF-8")


def build_employee_id_prompt(app_url, punch_type):
    """Prompt employee to enter their ID via the phone keypad."""
    root = etree.Element("CiscoIPPhoneInput")
    etree.SubElement(root, "Title").text = "Employee ID"
    etree.SubElement(root, "Prompt").text = "Enter your Employee ID"
    etree.SubElement(root, "URL").text = (
        f"{app_url}/ivr/authenticate?type={punch_type}"
    )

    item = etree.SubElement(root, "InputItem")
    etree.SubElement(item, "DisplayName").text = "Employee ID"
    etree.SubElement(item, "QueryStringParam").text = "employee_id"
    etree.SubElement(item, "DefaultValue").text = ""
    etree.SubElement(item, "InputFlags").text = "N"  # Numeric input only

    return etree.tostring(root, xml_declaration=True, encoding="UTF-8")


def build_confirmation_screen(title, message):
    """Display a confirmation or error message on the phone screen."""
    root = etree.Element("CiscoIPPhoneText")
    etree.SubElement(root, "Title").text = title
    etree.SubElement(root, "Text").text = message

    return etree.tostring(root, xml_declaration=True, encoding="UTF-8")


def build_status_screen(employee_name, last_punch_type, last_punch_time):
    """Show the employee their current clock status."""
    if last_punch_type:
        status = "Clocked In" if last_punch_type == "clock_in" else "Clocked Out"
        time_str = last_punch_time.strftime("%I:%M %p") if last_punch_time else "N/A"
        message = f"Employee: {employee_name}\nStatus: {status}\nLast punch: {time_str}"
    else:
        message = f"Employee: {employee_name}\nNo punches recorded today."

    root = etree.Element("CiscoIPPhoneText")
    etree.SubElement(root, "Title").text = "Clock Status"
    etree.SubElement(root, "Text").text = message

    return etree.tostring(root, xml_declaration=True, encoding="UTF-8")
