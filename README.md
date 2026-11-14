# EventSphere

**IT4123 – Agent Based Computing | ICA 02**

EventSphere is an agent-based venue booking and digital ticketing platform developed using Python, FastAPI, PostgreSQL and SQLAlchemy.

## Project Status

**Completed**
- Development environment setup
- FastAPI backend initialization
- PostgreSQL database connection
- Database models for 13 application tables
- Alembic database migrations

**In Progress**
- Secure user authentication and role-based access control
- Venue and event management
- Ticket booking and simulated payments
- QR-code ticket generation and verification
- Venue hire requests
- Multi-agent communication and decision-making
- Waitlist and notification features
- Frontend development, testing and deployment

## Technology Stack

- Python
- FastAPI
- PostgreSQL
- SQLAlchemy
- Alembic
- HTML, CSS, JavaScript and Bootstrap (planned)
- Pytest (planned)

## Local Setup

1. Clone the repository.
2. Create and activate a Python virtual environment.
3. Install dependencies:

   `python -m pip install -r requirements.txt`

4. Create a PostgreSQL database named `eventsphere_db`.
5. Configure the `DATABASE_URL` environment variable in a local `.env` file.
6. Apply database migrations:

   `python -m alembic upgrade head`

7. Start the development server:

   `python -m uvicorn app.main:app --reload`

8. Open `http://127.0.0.1:8000/docs`.

## Development Progress

| Stage | Description | Status |
|---|---|---|
| Steps 1–2 | Development tools and PostgreSQL setup | Completed |
| Step 3 | FastAPI project initialization | Completed |
| Step 4 | PostgreSQL integration | Completed |
| Step 5 | SQLAlchemy models and Alembic migrations | Completed |
| Step 6 | User authentication and roles | Pending |

## Security

Local passwords and environment secrets are excluded from Git using `.gitignore`. The platform will use simulated payments only.

## Assignment

IT4123 Agent Based Computing – ICA 02

This project is under active development.