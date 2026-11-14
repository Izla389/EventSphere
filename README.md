# EventSphere

**IT4123 – Agent Based Computing | ICA 02**

EventSphere is an agent-based venue booking and digital ticketing platform developed using Python, FastAPI, PostgreSQL, SQLAlchemy and Bootstrap.

The project aims to provide secure event management, venue booking, digital ticketing and intelligent decision-making through multiple communicating agents.

## Project Status

### Completed
- Development environment setup
- FastAPI backend initialization
- PostgreSQL database connection
- SQLAlchemy database models for 13 application tables
- Alembic database migrations
- Secure attendee registration
- User login and logout
- Argon2 password hashing
- Session-based authentication
- CSRF protection
- Role-based access control for admin, staff and attendees
- Admin and staff account creation through a local script
- Responsive registration, login and dashboard pages
- Six automated authentication tests passing

### In Progress
- Admin venue management (create, view, update and delete)

### Upcoming Features
- Event management and scheduling
- Ticket categories and pricing
- Ticket booking and simulated payments
- QR-code ticket generation and verification
- Private venue hire requests
- Multi-agent communication and decision-making
- Automated waitlist management
- User notifications
- Admin analytics dashboard
- Final responsive interface improvements
- Automated integration testing
- Public HTTPS deployment

## Technology Stack

**Backend**
- Python 3.11+
- FastAPI
- SQLAlchemy
- Pydantic

**Database**
- PostgreSQL
- Alembic

**Frontend**
- HTML
- CSS
- Bootstrap
- Jinja2 templates

**Authentication and Security**
- Argon2 password hashing using pwdlib
- Signed session cookies
- CSRF protection
- Role-based access control

**Testing**
- Pytest
- FastAPI TestClient
- SQLite in-memory test database

**Version Control**
- Git
- GitHub Desktop
- GitHub

## User Roles

EventSphere supports three user roles:

1. **Admin / Organiser** – Manages venues, events, bookings and platform operations.
2. **Gate Staff** – Verifies tickets and manages event entry.
3. **Attendee** – Registers, browses events, books tickets and manages reservations.

Access to protected features is enforced on the server.

## Local Setup

### 1. Clone the repository

Clone the EventSphere repository from GitHub and open the project folder.

### 2. Create a virtual environment

```powershell
python -m venv .venv
```

Activate it on Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

### 3. Install dependencies

```powershell
python -m pip install -r requirements.txt
```

### 4. Create the PostgreSQL database

Create a database named:

```text
eventsphere_db
```

### 5. Configure environment variables

Create a `.env` file in the project root.

Example:

```dotenv
DATABASE_URL=postgresql+psycopg://postgres:YOUR_URL_ENCODED_PASSWORD@localhost:5432/eventsphere_db
SECRET_KEY=YOUR_RANDOM_SECRET_KEY
SESSION_HTTPS_ONLY=false
```

Generate a secure secret key:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Replace the placeholders with your own local configuration.

If the PostgreSQL password contains special characters, URL-encode them in `DATABASE_URL`.

**Important:** Never commit `.env` or actual passwords to GitHub.

`SESSION_HTTPS_ONLY=false` is intended for local HTTP development only. Set it to `true` when deploying with HTTPS.

### 6. Apply database migrations

```powershell
python -m alembic upgrade head
```

### 7. Start the FastAPI server

```powershell
python -m uvicorn app.main:app --reload
```

### 8. Open the application

- Login: http://127.0.0.1:8000/login
- Registration: http://127.0.0.1:8000/register
- Dashboard: http://127.0.0.1:8000/dashboard
- API documentation: http://127.0.0.1:8000/docs
- Health check: http://127.0.0.1:8000/health
- Database check: http://127.0.0.1:8000/db-check

The dashboard requires authentication.

## Creating Admin and Staff Accounts

Public registration creates attendee accounts only.

Create an admin account locally:

```powershell
python -m scripts.create_user admin
```

Create a gate staff account:

```powershell
python -m scripts.create_user staff
```

Follow the terminal prompts to provide the account name, email address and password.

## Running Tests

Run the authentication tests:

```powershell
python -m pytest tests/test_auth.py -v
```

Run all available tests:

```powershell
python -m pytest tests/ -v
```

**Current verified result:** 6 authentication tests passed.

The tests cover password hashing, registration, CSRF validation, login/logout and role-based access restrictions.

## Development Progress

| Step | Description | Status |
|---|---|---|
| 1–2 | Development tools and PostgreSQL setup | Completed |
| 3 | FastAPI project initialization | Completed |
| 4 | PostgreSQL integration | Completed |
| 5 | SQLAlchemy models and Alembic migrations | Completed |
| 6 | Authentication, sessions, CSRF and user roles | Completed |
| 7 | Admin venue management | In Progress |
| 8 | Event management and scheduling | Pending |
| 9 | Ticket booking and simulated payments | Pending |
| 10 | QR tickets and check-in | Pending |
| 11 | Five-agent system and JSON communication | Pending |
| 12 | Automated waitlist and notifications | Pending |
| 13 | Private venue hire, dashboard and frontend completion | Pending |
| 14 | Final testing, deployment and submission | Pending |

## Agent-Based Architecture

EventSphere will include five agents:

1. **VenueAgent** – Handles venue availability, scheduling conflicts, private hire decisions, pricing and alternatives.
2. **BookingAgent** – Manages booking decisions, ticket limits, cancellations and refunds.
3. **TicketAgent** – Issues and validates digital tickets and QR-code check-ins.
4. **WaitlistAgent** – Manages waitlists, seat reoffers and automatic offer expiry.
5. **NotificationAgent** – Processes agent notifications and delivers user updates.

Agents will communicate using structured JSON messages, with message history stored for monitoring and debugging.

**Status:** Planned for upcoming development stages.

## Security

EventSphere uses:
- Hashed passwords instead of plaintext password storage
- Signed, HTTP-only session cookies
- CSRF protection for authentication forms
- Server-side role-based authorization
- Environment variables for sensitive configuration
- Git ignore rules to exclude local secrets

Payments will be simulated; real payment processing is outside the assignment scope.

Additional production security measures will be configured before public deployment.

## GitHub Development Workflow

The project is maintained using GitHub Desktop.

After each completed and tested development stage:

1. Review the changed files in GitHub Desktop.
2. Verify that private configuration files are excluded.
3. Create a descriptive commit.
4. Push the commit to GitHub.

This maintains a clear history of project development.

## Assignment

**Module:** IT4123 – Agent Based Computing  
**Assessment:** ICA 02  
**Project:** EventSphere

This project is under active development.
