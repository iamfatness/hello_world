"""Cisco AXL (Administrative XML) SOAP API client.

Used to provision and manage the CTI Route Point on CUCM.
This is optional - the route point can also be created manually via CUCM admin.

The AXL API uses SOAP/XML and requires an application user with
'Standard AXL API Access' role in CUCM.
"""

import logging
import urllib3
from requests import Session
from requests.auth import HTTPBasicAuth

logger = logging.getLogger(__name__)

# Suppress insecure HTTPS warnings when verify_ssl is disabled
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

AXL_NAMESPACE = "http://www.cisco.com/AXL/API/{version}"


class AXLClient:
    """Client for Cisco CUCM AXL SOAP API."""

    def __init__(self, host, username, password, version="14.0", verify_ssl=False):
        self.base_url = f"https://{host}:8443/axl/"
        self.version = version
        self.session = Session()
        self.session.auth = HTTPBasicAuth(username, password)
        self.session.verify = verify_ssl
        self.session.headers.update({
            "Content-Type": "text/xml",
            "SOAPAction": f'"CUCM:DB ver={version}"',
        })

    def _soap_request(self, operation, body_xml):
        """Send a SOAP request to the AXL API."""
        envelope = f"""<?xml version="1.0" encoding="UTF-8"?>
        <soapenv:Envelope
            xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
            xmlns:ns="{AXL_NAMESPACE.format(version=self.version)}">
            <soapenv:Body>
                <ns:{operation}>
                    {body_xml}
                </ns:{operation}>
            </soapenv:Body>
        </soapenv:Envelope>"""

        response = self.session.post(self.base_url, data=envelope, timeout=30)
        response.raise_for_status()
        return response.text

    def add_cti_route_point(self, device_name, description, directory_number,
                            partition="", css=""):
        """Create a CTI Route Point in CUCM.

        Args:
            device_name: Unique device name for the route point.
            description: Human-readable description.
            directory_number: The DN (phone number) to assign.
            partition: Route partition (optional).
            css: Calling Search Space (optional).
        """
        body = f"""
            <ctiRoutePoint>
                <name>{device_name}</name>
                <description>{description}</description>
                <product>CTI Route Point</product>
                <class>CTI Route Point</class>
                <protocol>SCCP</protocol>
                <callingSearchSpaceName>{css}</callingSearchSpaceName>
                <lines>
                    <line>
                        <index>1</index>
                        <dirn>
                            <pattern>{directory_number}</pattern>
                            <routePartitionName>{partition}</routePartitionName>
                        </dirn>
                    </line>
                </lines>
            </ctiRoutePoint>
        """
        logger.info("Creating CTI Route Point: %s (%s)", device_name, directory_number)
        return self._soap_request("addCtiRoutePoint", body)

    def get_cti_route_point(self, device_name):
        """Retrieve a CTI Route Point by device name."""
        body = f"<name>{device_name}</name>"
        return self._soap_request("getCtiRoutePoint", body)

    def remove_cti_route_point(self, device_name):
        """Remove a CTI Route Point from CUCM."""
        body = f"<name>{device_name}</name>"
        logger.info("Removing CTI Route Point: %s", device_name)
        return self._soap_request("removeCtiRoutePoint", body)
