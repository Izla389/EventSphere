# EventSphere – Multi-Agent Venue Booking and Digital Ticketing Platform

![Python](https://img.shields.io/badge/Python-3.11%2B-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-Backend-green)
![PostgreSQL](https://img.shields.io/badge/Database-PostgreSQL-blue)
![Pytest](https://img.shields.io/badge/Testing-Pytest-orange)
![Deployment](https://img.shields.io/badge/Deployment-Vercel-black)

## 1. Project Overview

**EventSphere** is a mobile-friendly venue booking and digital ticketing platform developed as part of the IT4123 – Agent Based Computing Practical (ICA 02) assignment.

The platform provides a centralized system for managing university events, booking tickets, hiring venues and verifying digital tickets through QR codes.

EventSphere uses a multi-agent architecture in which autonomous software agents cooperate to make decisions and manage different activities within the platform.

The system supports three types of users:

- **Admin / Organiser:** Manages venues, events, ticket categories, bookings and event activities.
- **Gate Staff:** Verifies digital tickets and manages attendee check-ins.
- **Attendee:** Browses events, books tickets, manages bookings and requests private venue hire.

The application is accessible through a web browser and does not require users to install a mobile application.

## 2. Live Application

| Resource | Link |
|---|---|
| Live Website | https://event-sphere-taupe-omega.vercel.app |
| API Documentation | https://event-sphere-taupe-omega.vercel.app/docs |
| GitHub Repository | https://github.com/Izla389/EventSphere |

**Deployment Architecture:**
- Application hosting: Vercel
- Production database: Neon PostgreSQL
- Source code management: GitHub
- Backend framework: FastAPI

## 3. Main Features

### User Management
- User registration and login.
- Secure password hashing.
- Role-based access control.
- Separate access for Admin, Staff and Attendee.

### Venue Management
- Create and update venues.
- Manage venue names and locations.
- Configure venue capacity.
- Set hourly venue hire rates.
- Manage private hire availability.

### Event Management
- Create and update events.
- Assign venues to events.
- Configure event dates and times.
- Create ticket categories.
- Set ticket prices and quantities.
- Publish or cancel events.

### Ticket Booking
- Browse available events.
- Search events by keywords.
- Filter events by category.
- View ticket availability.
- Book one or more tickets.
- View booking history.
- Cancel bookings according to the refund policy.
- Record simulated payment references.

### Digital Tickets and Check-in
- Generate unique QR-based digital tickets.
- Display digital tickets to attendees.
- Scan tickets using a mobile device.
- Support manual ticket code entry.
- Validate ticket status.
- Prevent duplicate ticket check-ins.

### Private Venue Hire
- Submit private venue hire requests.
- Specify booking dates and times.
- Enter event purpose and guest count.
- Evaluate venue availability.
- Calculate venue hire prices.
- Provide alternative venue or time suggestions when appropriate.

### Organiser Dashboard
- Monitor event activities.
- View ticket sales.
- Monitor attendance and check-ins.
- View relevant agent communication records.

## 4. Multi-Agent Architecture

EventSphere consists of five main software agents.

### 4.1 VenueAgent

**Goal:** Manage venue availability and prevent scheduling conflicts.

Responsibilities:
- Check venue availability.
- Validate event schedules.
- Prevent overlapping reservations.
- Evaluate private venue hire requests.
- Calculate venue hire prices.
- Suggest alternative venues or time slots.

### 4.2 BookingAgent

**Goal:** Manage ticket bookings fairly and prevent ticket overselling.

Responsibilities:
- Receive booking requests.
- Validate ticket quantities.
- Check available ticket capacity.
- Accept or refuse booking requests.
- Process booking cancellations.
- Calculate refunds.
- Coordinate with other agents.

### 4.3 TicketAgent

**Goal:** Ensure the validity and uniqueness of digital tickets.

Responsibilities:
- Generate unique ticket codes.
- Generate QR codes.
- Validate ticket information.
- Verify event details.
- Prevent duplicate check-ins.
- Reject invalid or cancelled tickets.

### 4.4 WaitlistAgent

**Goal:** Manage customers waiting for unavailable tickets.

Responsibilities:
- Maintain waitlist information.
- Select eligible customers when tickets become available.
- Offer released tickets.
- Manage temporary ticket holds.
- Handle expired offers.
- Re-offer unclaimed tickets when appropriate.

### 4.5 NotificationAgent

**Goal:** Deliver relevant notifications to users.

Responsibilities:
- Receive messages from other agents.
- Process event-related notifications.
- Notify users about booking updates.
- Communicate ticket availability.
- Deliver important event information.

### 4.6 Agent Communication

The agents communicate using structured JSON messages.

The communication performatives include:

| Performatives | Description |
|---|---|
| REQUEST | Request an operation from another agent. |
| AGREE | Accept a request. |
| REFUSE | Reject a request with a reason. |
| PROPOSE | Suggest an alternative. |
| INFORM | Share information. |
| FAILURE | Report an unsuccessful operation. |

Agent messages contain:
- Sender
- Receiver
- Performative
- Content
- Conversation ID

**Note:** The detailed agent rules, persistent state and communication flows should reflect the actual implementation in the source code.

## 5. Technologies Used

| Technology | Purpose |
|---|---|
| Python 3.11+ | Backend programming |
| FastAPI | REST API and backend framework |
| Pydantic | Data validation |
| PostgreSQL | Relational database |
| Neon | Cloud PostgreSQL hosting |
| SQLAlchemy | Database ORM |
| Alembic | Database migrations |
| HTML | Frontend structure |
| CSS | Frontend styling |
| JavaScript | Frontend functionality |
| Jinja2 | HTML templating |
| Pytest | Automated testing |
| Git | Version control |
| GitHub | Source code repository |
| Vercel | Application deployment |

## 6. Project Structure

The main project structure is:

```text
EventSphere/
│
├── app/
│   ├── agents/
│   │   ├── venue_agent.py
│   │   ├── booking_agent.py
│   │   ├── ticket_agent.py
│   │   ├── waitlist_agent.py
│   │   └── notification_agent.py
│   │
│   ├── routers/
│   ├── templates/
│   ├── static/
│   ├── main.py
│   ├── config.py
│   ├── database.py
│   └── models.py
│
├── tests/
│   ├── test_auth.py
│   ├── test_events.py
│   ├── test_venues.py
│   ├── test_attendee_booking.py
│   ├── test_checkin_routes.py
│   ├── test_payment_routes.py
│   ├── test_staff_assignments.py
│   └── test_staff_dashboard.py
│
├── alembic/
│
├── scripts/
│
├── index.py
├── .python-version
├── requirements.txt
├── alembic.ini
├── README.md
└── .env
```

The listed structure represents the main application areas. Individual filenames should be adjusted to match the actual repository.

## 7. Installation and Local Setup

Follow these steps to run EventSphere on a local Windows development environment.

### Prerequisites

Install the following:

- Python 3.11 or newer.
- PostgreSQL.
- Git.
- Visual Studio Code (recommended).

### Step 1: Clone the Repository

```bash
git clone https://github.com/Izla389/EventSphere.git
```

Navigate into the project directory:

```bash
cd EventSphere
```

### Step 2: Create a Virtual Environment

```bash
python -m venv .venv
```

Activate the virtual environment using PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

### Step 3: Install Dependencies

```bash
python -m pip install --upgrade pip
```

Install the required packages:

```bash
pip install -r requirements.txt
```

### Step 4: Configure Environment Variables

Create a `.env` file in the project root directory.

Add the following variables:

```env
DATABASE_URL=postgresql+psycopg://username:password@localhost:5432/eventsphere_db

SECRET_KEY=your_secure_random_secret_key

SESSION_HTTPS_ONLY=False
```

**Important:**

- For local development, use your local PostgreSQL connection string.
- For production deployment, configure the Neon PostgreSQL connection string in Vercel.
- Generate a secure and unique `SECRET_KEY`.
- Never commit `.env` to GitHub.
- Do not share database passwords or secret keys publicly.

### Step 5: Configure the Database

Create a PostgreSQL database named:

```text
eventsphere_db
```

Ensure that PostgreSQL is running and the database credentials match the `.env` configuration.

### Step 6: Run Database Migrations

Apply the database migrations:

```bash
python -m alembic upgrade head
```

Check the current migration version:

```bash
python -m alembic current
```

### Step 7: Start the Application

Run the FastAPI application:

```bash
python -m uvicorn app.main:app --reload
```

Open the application in your browser:

```text
http://127.0.0.1:8000
```

Open the API documentation:

```text
http://127.0.0.1:8000/docs
```

## 8. Environment Variables

The application uses environment variables to manage sensitive configuration information.

| Variable | Description |
|---|---|
| DATABASE_URL | PostgreSQL database connection string |
| SECRET_KEY | Secret key used by the application |
| SESSION_HTTPS_ONLY | Controls HTTPS-only session cookies |

### Local Environment

Local development uses the local PostgreSQL database.

### Production Environment

Production uses the Neon PostgreSQL database.

Configure the production environment variables through:

**Vercel Dashboard → EventSphere Project → Settings → Environment Variables**

Add the required variables:

```text
DATABASE_URL
SECRET_KEY
SESSION_HTTPS_ONLY
```

Use the appropriate production values and enable HTTPS-only session cookies when the application is served over HTTPS.

## 9. Database Migrations

EventSphere uses Alembic to manage database schema changes.

Useful commands:

Check the current migration:

```bash
python -m alembic current
```

Display migration history:

```bash
python -m alembic history
```

Display available migration heads:

```bash
python -m alembic heads
```

Apply migrations:

```bash
python -m alembic upgrade head
```

## 10. Running Tests

EventSphere uses Pytest for automated testing.

### Run All Tests

```bash
python -m pytest -q
```

### Run Tests with Detailed Output

```bash
python -m pytest -v
```

### Run a Specific Test File

```bash
python -m pytest tests/test_auth.py -v
```

### Display Collected Tests

```bash
python -m pytest --collect-only -q
```

### Test Coverage Requirements

The assessment requires at least 10 meaningful tests.

Testing should include:

1. User registration.
2. User authentication.
3. VenueAgent decision-making.
4. BookingAgent decision-making.
5. TicketAgent validation.
6. WaitlistAgent functionality.
7. NotificationAgent functionality.
8. Ticket overbooking prevention.
9. Duplicate check-in prevention.
10. Role-based access control.

Run the tests and record the actual results before submission.

## 11. Demo Accounts

The application provides three types of demonstration accounts.

| User Role | Email | Password |
|---|---|---|
| Admin | izlaizzath@gmail.com | abc123456789 |
| Staff | uovizla@gmail.com | uov123456789abc |
| Attendee | hima@gmail.com| hima123456789 |

Use the actual working demo account credentials when preparing the final README.

Do not include personal account credentials.

## 12. Deployment

EventSphere is deployed using Vercel with Neon PostgreSQL as its production database.

### Deployment Components

| Component | Service |
|---|---|
| Application hosting | Vercel |
| Database hosting | Neon |
| Source code | GitHub |
| Backend | FastAPI |
| Database | PostgreSQL |

### Deployment Process

1. Push the application source code to GitHub.
2. Import the GitHub repository into Vercel.
3. Configure the required environment variables.
4. Configure the Python runtime and application entry point.
5. Deploy the application.
6. Verify the deployment through the public HTTPS URL.
7. Verify database connectivity and API functionality.

### Production Links

**Live Application:**

https://event-sphere-taupe-omega.vercel.app

**FastAPI API Documentation:**

https://event-sphere-taupe-omega.vercel.app/docs

**Neon Database Console:**

https://console.neon.tech/

## 13. Security Considerations

The application considers the following security requirements:

- Passwords must be hashed before storage.
- Role-based authorization must protect administrative and staff operations.
- Sensitive credentials must be stored in environment variables.
- Database connections must use secure credentials.
- Input validation must be performed using Pydantic.
- CSRF protection must be applied to relevant form-based operations.
- Production sessions must use appropriate HTTPS security settings.

### Simulated Payments

EventSphere uses simulated payments for assessment purposes.

No real bank account, credit card or payment gateway is connected.

## 14. Important Assessment Requirements

The project is developed according to the IT4123 ICA 02 assignment requirements.

The main assessment areas include:

- User registration and authentication.
- Role-based access control.
- Venue management.
- Event management.
- Ticket booking and cancellation.
- QR-based digital tickets.
- Ticket verification and check-in.
- Private venue hire.
- Organiser dashboard.
- Five cooperating autonomous agents.
- Structured agent communication.
- Reactive and proactive agent behaviour.
- Persistent agent state.
- Automated testing.
- Public HTTPS deployment.

## 15. Future Improvements

Possible future enhancements include:

- Enhanced notification services.
- Advanced event search and filtering.
- More detailed analytics and reporting.
- Improved mobile user experience.
- Additional agent decision-making capabilities.
- Enhanced monitoring of agent communication.

## 16. Author

**Project Name:** EventSphere

**Course:** IT4123 – Agent Based Computing Practical

**Assessment:** ICA 02

**Repository:** https://github.com/Izla389/EventSphere

**Live Application:** https://event-sphere-taupe-omega.vercel.app

---

## License

This project was developed for academic purposes as part of the IT4123 Agent Based Computing Practical assessment.
