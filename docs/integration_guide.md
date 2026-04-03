# Integration Guide: Cisco CUCM & UKG Pro WFM Connections

This document describes how to connect the Cisco-UKG Clock application to both
the Cisco Unified Communications Manager (CUCM) phone platform and the UKG Pro
Workforce Management API.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [UKG Pro WFM API Connection](#ukg-pro-wfm-api-connection)
   - [Prerequisites](#ukg-prerequisites)
   - [Obtaining API Credentials](#obtaining-ukg-api-credentials)
   - [Configuration](#ukg-configuration)
   - [Authentication Flow](#ukg-authentication-flow)
   - [API Endpoints Used](#ukg-api-endpoints-used)
   - [Testing the Connection](#testing-the-ukg-connection)
   - [Failover & Retry Behavior](#failover--retry-behavior)
3. [Cisco CUCM Connection](#cisco-cucm-connection)
   - [Prerequisites](#cisco-prerequisites)
   - [CUCM Administration Setup](#cucm-administration-setup)
   - [CTI Route Point Configuration](#cti-route-point-configuration)
   - [Application User Setup](#application-user-setup)
   - [HTTP Trigger / Phone Service Configuration](#http-trigger--phone-service-configuration)
   - [Configuration](#cisco-configuration)
   - [AXL API Connection (Optional)](#axl-api-connection-optional)
   - [Testing the Connection](#testing-the-cisco-connection)
4. [Network Requirements](#network-requirements)
5. [Configuration Methods](#configuration-methods)
6. [Troubleshooting](#troubleshooting)

---

## Architecture Overview

```
┌──────────────┐          ┌──────────────────┐          ┌──────────────────┐
│              │  SIP/     │                  │  HTTP     │                  │
│  Cisco IP    │──Call────>│  Cisco CUCM      │──Webhook─>│  This App        │
│  Phone       │          │  CTI Route Point │          │  (Flask)         │
│              │<─────────│                  │<─────────│                  │
│  XML Display │  XML Svc │                  │  XML Resp│                  │
└──────────────┘          └──────────────────┘          └───────┬──────────┘
                                                                │
                                                                │ REST API
                                                                │ (HTTPS)
                                                                v
                                                        ┌──────────────────┐
                                                        │  UKG Pro WFM     │
                                                        │  Cloud API       │
                                                        └──────────────────┘
```

**Call flow summary:**

1. Employee dials the clock-in extension on their Cisco IP phone
2. CUCM routes the call to a CTI Route Point
3. The route point triggers an HTTP request to this application's webhook
4. The application identifies the employee and serves XML menu screens to the phone
5. The employee selects Clock In or Clock Out
6. The application records the punch locally and submits it to UKG via REST API

---

## UKG Pro WFM API Connection

### UKG Prerequisites

- An active UKG Pro Workforce Management (formerly Kronos) tenant
- Administrator access to the UKG Developer Hub / API management console
- An API application registered with OAuth2 credentials
- A service account user with permissions to submit time punches
- Network access from the application server to UKG's cloud API endpoints

### Obtaining UKG API Credentials

You will need **seven** credential values from UKG. Here is where to find each:

| Credential | Where to Find It |
|---|---|
| **Base URL** | Your tenant URL, typically `https://service5.ultipro.com` or `https://your-company.ultipro.com`. Found in UKG admin under **System Configuration > Security > Web Services**. |
| **API Key** | Generated in UKG Developer Hub when you register an API application. Go to **Menu > Administration > System Configuration > Security > Service Account Administration** or the UKG Developer Portal. |
| **Client ID** | Provided when you create an OAuth2 application in the UKG Developer Hub. |
| **Client Secret** | Provided alongside the Client ID. Store securely — it cannot be retrieved again after initial creation. |
| **Username** | A UKG service account username with API access and timekeeping permissions. Create a dedicated service account — do not use a personal login. |
| **Password** | The password for the service account above. |
| **User API Key** | Also called the "US-Customer-Api-Key". Found in **System Configuration > Security > Service Account Administration**. This identifies your company/tenant to UKG's API gateway. |

**Required UKG Roles for the Service Account:**

The service account must have these permissions:
- Timekeeping > Punches > Add/Edit
- Personnel > Employee > View (for employee validation)
- Web Services > API Access

### UKG Configuration

Configuration can be set in two ways:

**Option A: Environment Variables (`.env` file)**

```bash
UKG_BASE_URL=https://service5.ultipro.com
UKG_API_KEY=your-api-key-here
UKG_CLIENT_ID=your-client-id-here
UKG_CLIENT_SECRET=your-client-secret-here
UKG_USERNAME=your-service-account-username
UKG_PASSWORD=your-service-account-password
UKG_USER_API_KEY=your-us-customer-api-key
```

**Option B: Admin Portal (recommended for ongoing management)**

1. Navigate to `http://<app-host>:5000/admin/config`
2. Fill in the **UKG API Connection** section
3. Click **Save Configuration**
4. Click **Test Connection** to verify

Settings saved via the admin portal are stored in the database and persist
across restarts. They take priority over environment variables.

### UKG Authentication Flow

The application authenticates with UKG using an OAuth2 Resource Owner Password
Credentials (ROPC) flow:

```
POST {base_url}/authentication/token
Content-Type: application/x-www-form-urlencoded
Api-Key: {api_key}
US-Customer-Api-Key: {user_api_key}

grant_type=password
&client_id={client_id}
&client_secret={client_secret}
&username={username}
&password={password}
```

**Response:**
```json
{
    "access_token": "eyJ0eXAiOiJKV1Qi...",
    "token_type": "bearer",
    "expires_in": 3600
}
```

The application automatically:
- Caches the access token after first authentication
- Refreshes the token 60 seconds before expiry
- Re-authenticates if a request returns 401

### UKG API Endpoints Used

| Endpoint | Method | Purpose |
|---|---|---|
| `/authentication/token` | POST | Obtain OAuth2 access token |
| `/personnel/v1/employee-punches` | POST | Submit a clock-in or clock-out punch |
| `/personnel/v1/employee-punches` | GET | Retrieve an employee's punches for a date |
| `/personnel/v1/employees/{id}` | GET | Validate that an employee exists |

**Time Punch Submission Payload:**

```json
{
    "employeeIdentifier": "UKG-12345",
    "punchType": "IN",
    "punchDateTime": "2026-04-03T08:00:00",
    "punchSource": "PHONE_SYSTEM"
}
```

- `punchType` is `"IN"` for clock-in, `"OUT"` for clock-out
- `punchDateTime` is in ISO 8601 format (UTC)
- `punchSource` is set to `"PHONE_SYSTEM"` to identify the origin

**All authenticated API requests include these headers:**

```
Authorization: Bearer {access_token}
Content-Type: application/json
Api-Key: {api_key}
US-Customer-Api-Key: {user_api_key}
```

### Testing the UKG Connection

**From the Admin Portal:**

1. Go to `http://<app-host>:5000/admin/config`
2. Enter your credentials
3. Click **Test Connection** next to the UKG section
4. A green "Connected successfully" message confirms the connection

**From the command line:**

```bash
curl -X POST http://localhost:5000/admin/config/test-ukg
# Returns: {"success": true} or {"success": false, "error": "..."}
```

### Failover & Retry Behavior

The application is designed to **never lose a punch**, even when UKG is
unreachable:

1. **Every punch is saved to the local SQLite database first**, before
   attempting the UKG API call.
2. If the UKG API call fails (timeout, 5xx error, network error), the punch
   is marked as `failed` locally and the employee still sees a success
   confirmation on their phone.
3. A **background retry worker** runs as a daemon thread, scanning for
   unsynced punches every 30 seconds.
4. Retries use **exponential backoff**:

   | Retry # | Wait Time |
   |---------|-----------|
   | 1       | 30 seconds |
   | 2       | 1 minute |
   | 3       | 2 minutes |
   | 4       | 5 minutes |
   | 5       | 15 minutes |
   | 6       | 30 minutes |
   | 7+      | 1 hour |

5. Maximum **48 retries** (~24 hours of retry coverage).
6. If all retries are exhausted, the punch remains in the database with status
   `failed` and can be manually retried from the admin portal.

**Monitoring failed syncs:**

- **Dashboard** (`/admin/`): Shows pending and failed sync counts in real time
- **Punches page** (`/admin/punches`): Filter by status to see all failed
  punches; use the **Retry Failed** button for immediate re-sync
- **Retry worker stats** are displayed on the dashboard: total retried,
  succeeded, and exhausted counts

---

## Cisco CUCM Connection

### Cisco Prerequisites

- Cisco Unified Communications Manager (CUCM) version 10.x or later
- Administrator access to CUCM Administration web interface
- An available Directory Number (DN) / extension for the clock-in line
- Network access from CUCM to the application server on port 5000 (or your
  configured port)
- (Optional) AXL API access for programmatic provisioning

### CUCM Administration Setup

All Cisco configuration is done through the **CUCM Administration** web
interface at `https://<cucm-host>/ccmadmin`.

#### Step 1: Create an Application User

The application user allows CUCM to communicate with the clock-in app.

1. Navigate to **User Management > Application User**
2. Click **Add New**
3. Fill in:
   - **User ID:** `ClockInApp` (or your preferred name)
   - **Password:** Choose a strong password
   - **Confirm Password:** Re-enter the password
4. Under **Permissions Information**, add these roles:
   - `Standard CTI Allow Control of Phones supporting Connected Xfer and conf`
   - `Standard CTI Allow Control of All Devices`
   - `Standard CTI Enabled`
   - `Standard AXL API Access` (only needed if using programmatic provisioning)
5. Click **Save**

#### Step 2: Create a CTI Route Point

A CTI Route Point is a virtual device that receives calls and triggers
application logic — it does not ring a physical phone.

1. Navigate to **Device > CTI Route Point**
2. Click **Add New**
3. Fill in:
   - **Device Name:** `ClockInRoutePoint` (must match your config)
   - **Description:** `Employee Clock-In/Out System`
   - **Device Pool:** Select your default device pool
   - **Calling Search Space:** Select the CSS that allows internal calls
   - **Protocol:** SCCP
4. Click **Save**
5. On the left panel, click **Line [1] - Add a new DN**
6. Configure the Directory Number:
   - **Directory Number:** `5000` (or your preferred extension)
   - **Route Partition:** Select your internal partition
   - **Description:** `Clock In/Out Line`
   - **Alerting Name:** `Time Clock`
   - **Display (Internal Caller ID):** `Time Clock`
7. Click **Save**

#### Step 3: Associate the Application User with the Route Point

1. Go back to **User Management > Application User**
2. Select the `ClockInApp` user
3. Under **Device Information**, add `ClockInRoutePoint` to the
   **Controlled CTI Devices** list
4. Click **Save**

### HTTP Trigger / Phone Service Configuration

The CTI Route Point needs to notify the application when a call arrives. This
is done by configuring a **Phone Service** or **HTTP trigger** that points to
the application's webhook endpoint.

#### Option A: Cisco IP Phone Service (Recommended)

This approach makes the phone fetch XML pages from the application:

1. Navigate to **Device > Device Settings > Phone Services**
2. Click **Add New**
3. Fill in:
   - **Service Name:** `Time Clock`
   - **Service URL:**
     ```
     http://<app-host>:5000/webhook/call?callerid=#DEVICENAME#&callednumber=#DIRN#
     ```
   - **Service Category:** XML Service
   - **Service Type:** Standard IP Phone Service
4. Click **Save**
5. Subscribe the CTI Route Point to this service:
   - Go to **Device > CTI Route Point**, select `ClockInRoutePoint`
   - Click **Subscribe/Unsubscribe Services**
   - Add the `Time Clock` service

**CUCM URL substitution variables you can use:**

| Variable | Description |
|---|---|
| `#DEVICENAME#` | Name of the calling device |
| `#DIRN#` | Directory number being called |
| `#SIPURI#` | SIP URI of the caller |

#### Option B: Direct HTTP Trigger via Dial Rules

For environments using CUCM's application dial rules:

1. Configure a **Route Pattern** or **Translation Pattern** that matches
   the clock-in extension (e.g., `5000`)
2. Set the route to forward to an **HTTP URL trigger** pointing to:
   ```
   http://<app-host>:5000/webhook/call
   ```
3. Configure the trigger to pass `callerid` and `callednumber` as parameters

### Cisco Configuration

**Option A: Environment Variables (`.env` file)**

```bash
# CUCM Connection
CUCM_HOST=cucm.example.com       # CUCM publisher hostname or IP
CUCM_USERNAME=ClockInApp          # Application User ID
CUCM_PASSWORD=your-password       # Application User password
CUCM_VERSION=14.0                 # CUCM version (e.g., 12.5, 14.0, 15.0)

# CTI Route Point
CTI_ROUTE_POINT_DN=5000           # Extension number assigned to the route point
CTI_DEVICE_NAME=ClockInRoutePoint # Device name in CUCM
```

**Option B: Admin Portal**

1. Navigate to `http://<app-host>:5000/admin/config`
2. Fill in the **Cisco CUCM Connection** section
3. Click **Save Configuration**
4. Click **Test Connection** to verify AXL connectivity

### AXL API Connection (Optional)

The AXL (Administrative XML) SOAP API can be used to programmatically create
and manage the CTI Route Point instead of doing it manually in CUCM admin.

**AXL API details:**

- **Protocol:** HTTPS (port 8443)
- **Endpoint:** `https://<cucm-host>:8443/axl/`
- **Authentication:** HTTP Basic Auth using the Application User credentials
- **Content-Type:** `text/xml`
- **SOAPAction header:** `"CUCM:DB ver={version}"` (e.g., `"CUCM:DB ver=14.0"`)

**AXL operations used by this application:**

| Operation | Purpose |
|---|---|
| `addCtiRoutePoint` | Create a new CTI Route Point device |
| `getCtiRoutePoint` | Retrieve route point details (used for connection testing) |
| `removeCtiRoutePoint` | Remove a route point (cleanup) |

**Example AXL SOAP request (addCtiRoutePoint):**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope
    xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
    xmlns:ns="http://www.cisco.com/AXL/API/14.0">
    <soapenv:Body>
        <ns:addCtiRoutePoint>
            <ctiRoutePoint>
                <name>ClockInRoutePoint</name>
                <description>Employee Clock-In/Out System</description>
                <product>CTI Route Point</product>
                <class>CTI Route Point</class>
                <protocol>SCCP</protocol>
                <lines>
                    <line>
                        <index>1</index>
                        <dirn>
                            <pattern>5000</pattern>
                        </dirn>
                    </line>
                </lines>
            </ctiRoutePoint>
        </ns:addCtiRoutePoint>
    </soapenv:Body>
</soapenv:Envelope>
```

### Cisco IP Phone XML Services

When a call arrives, the application serves XML documents to the Cisco IP
phone's display. These are standard Cisco IP Phone Services XML types:

| XML Type | Used For |
|---|---|
| `CiscoIPPhoneMenu` | Main menu (Clock In / Clock Out / Check Status) |
| `CiscoIPPhoneInput` | Employee ID entry prompt (numeric keypad input) |
| `CiscoIPPhoneText` | Confirmation and status messages |

**Compatible phone models:** Any Cisco IP phone that supports XML services,
including 7900 series, 8800 series, 9800 series, and Webex Desk devices.

### Testing the Cisco Connection

**From the Admin Portal:**

1. Go to `http://<app-host>:5000/admin/config`
2. Enter your CUCM credentials
3. Click **Test Connection** next to the CUCM section
4. This tests AXL API connectivity by querying the CTI Route Point

**Manual verification:**

1. From a Cisco IP phone on the same CUCM cluster, dial the route point
   extension (e.g., `5000`)
2. The phone screen should display the **Time Clock** menu with options
   for Clock In, Clock Out, and Check Status
3. Check the application logs for the incoming webhook:
   ```
   Call webhook: caller=1001, called=5000, device=SEP001122334455
   ```

---

## Network Requirements

| Source | Destination | Port | Protocol | Purpose |
|---|---|---|---|---|
| CUCM | Application server | 5000 (TCP) | HTTP | Call webhooks, XML services |
| Cisco IP Phones | Application server | 5000 (TCP) | HTTP | XML service pages |
| Application server | CUCM | 8443 (TCP) | HTTPS | AXL SOAP API (optional) |
| Application server | UKG Cloud | 443 (TCP) | HTTPS | UKG REST API |

**Firewall considerations:**

- The application server must be reachable from both CUCM and the IP phones
- If CUCM and the phones are on a voice VLAN, ensure routing allows HTTP
  traffic to the application server
- UKG API calls go to the public internet — ensure outbound HTTPS is allowed
- No inbound internet access is required

---

## Configuration Methods

The application supports two configuration methods. Settings saved via the
admin portal take priority over environment variables.

| Method | When to Use |
|---|---|
| **Environment variables** (`.env` file) | Initial deployment, CI/CD, Docker containers |
| **Admin portal** (`/admin/config`) | Ongoing management, credential rotation, testing |

When you save settings in the admin portal, they are stored in the SQLite
database (`system_config` table) and loaded on each request. This means you
can change UKG or CUCM credentials without restarting the application.

---

## Troubleshooting

### UKG Connection Issues

| Symptom | Likely Cause | Resolution |
|---|---|---|
| `401 Unauthorized` | Invalid credentials or expired token | Verify API key, client ID/secret, and service account credentials in admin config. Check that the service account is not locked in UKG. |
| `403 Forbidden` | Missing API permissions | Ensure the service account has Timekeeping Punch Add/Edit permissions. |
| `Connection timeout` | Network/firewall issue | Verify the app server can reach the UKG base URL on port 443. Check proxy settings if applicable. |
| `404 Not Found` on punch endpoint | Wrong base URL | Verify the base URL matches your tenant (e.g., `https://service5.ultipro.com`). |
| Punches stuck in "pending" | UKG unreachable | Check the dashboard for retry worker status. The worker will retry automatically. Use the manual retry button if needed. |

### Cisco Connection Issues

| Symptom | Likely Cause | Resolution |
|---|---|---|
| Phone shows "Host Not Found" | App server unreachable from phone network | Check firewall rules and routing between voice VLAN and app server. |
| Phone shows blank screen on call | Service URL misconfigured | Verify the Phone Service URL in CUCM includes the correct app server hostname and port. |
| No webhook received | CTI Route Point not triggering | Verify the route point DN is correct, the Application User controls the device, and the Phone Service is subscribed. |
| AXL test fails with `Connection refused` | Wrong CUCM host or port | Verify CUCM hostname and ensure port 8443 is accessible. |
| AXL test fails with `401` | Wrong Application User credentials | Verify the username/password and that the user has `Standard AXL API Access` role. |
| Caller not recognized | Caller ID not in employee roster | Add the employee's phone number as their Caller ID in the admin portal under Employees. |
