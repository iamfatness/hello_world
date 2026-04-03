# Cisco-UKG Clock Integration

A Python application that connects Cisco IP phone systems with UKG Pro Workforce Management for employee time tracking. Employees call a designated phone number and use the phone's display to clock in/out. Punches are recorded locally and synced to UKG.

## Architecture

```
┌──────────────┐     ┌─────────────────┐     ┌──────────────┐
│  Cisco IP    │────>│  CUCM            │────>│  This App    │
│  Phone       │     │  CTI Route Point │     │  (Flask)     │
│              │<────│                  │<────│              │
│  XML Display │     │  HTTP Trigger    │     │  XML Services│
└──────────────┘     └─────────────────┘     └──────┬───────┘
                                                     │
                                              ┌──────▼───────┐
                                              │  UKG Pro WFM │
                                              │  REST API    │
                                              └──────────────┘
```

### Call Flow

1. Employee dials the clock-in extension (CTI Route Point)
2. CUCM sends an HTTP trigger to `/webhook/call`
3. App looks up caller by Caller ID
   - **Known caller** → shows main menu (Clock In / Clock Out / Check Status)
   - **Unknown caller** → prompts for Employee ID via phone keypad
4. Employee selects an action
5. App records the punch in SQLite and submits to UKG API
6. Confirmation displayed on phone screen

## Setup

### Prerequisites

- Python 3.10+
- Cisco CUCM with CTI Route Point configured
- UKG Pro WFM API credentials
- Network connectivity between this app and both CUCM and UKG

### Installation

```bash
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your Cisco CUCM and UKG credentials
```

### CUCM Configuration

1. **Create a CTI Route Point** in CUCM Administration
   - Device > CTI Route Point > Add New
   - Assign a Directory Number (e.g., 5000)
2. **Create an Application User** with CTI permissions
3. **Configure HTTP Trigger** to point to `http://<app-host>:5000/webhook/call`
   - Pass `callerid` and `callednumber` as query parameters

### Running

```bash
# Development
python app.py

# Production
gunicorn "app:create_app()" -b 0.0.0.0:5000 -w 4
```

## API Endpoints

### Phone IVR (Cisco XML Services)
| Endpoint | Description |
|---|---|
| `GET /ivr/menu` | Main clock-in/out menu |
| `GET /ivr/punch?type=clock_in` | Clock in prompt |
| `GET /ivr/authenticate` | Validate employee ID and record punch |
| `GET /ivr/status` | Check current clock status |

### Webhooks
| Endpoint | Description |
|---|---|
| `GET/POST /webhook/call` | CUCM call event webhook |
| `GET /webhook/health` | Health check |

### Admin API
| Endpoint | Description |
|---|---|
| `GET /api/employees` | List all employees |
| `POST /api/employees` | Register a new employee |
| `DELETE /api/employees/<id>` | Remove an employee |
| `GET /api/punches` | List time punches (filterable) |
| `POST /api/punches/retry` | Retry failed UKG syncs |

### Register an Employee

```bash
curl -X POST http://localhost:5000/api/employees \
  -H "Content-Type: application/json" \
  -d '{
    "employee_id": "EMP001",
    "name": "John Doe",
    "phone_extension": "1001",
    "caller_id": "5551234567",
    "ukg_employee_id": "UKG-12345"
  }'
```

## Testing

```bash
pip install pytest
pytest tests/ -v
```
