
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.models import (
    Booking,
    BookingStatus,
    Event,
    EventStaffAssignment,
    EventStatus,
    Ticket,
    TicketCategory,
    TicketStatus,
    User,
    UserRole,
    Venue,
)
from app.security import hash_password


PASSWORD = "StrongPassword123!"


# ----------------------------------------------
# Test database setup
# ----------------------------------------------

@pytest.fixture
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    Base.metadata.create_all(bind=engine)

    TestingSession = sessionmaker(
        bind=engine,
        expire_on_commit=False,
    )

    def override_get_db():
        with TestingSession() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db

    try:
        with TestClient(
            app,
            follow_redirects=False,
        ) as test_client:
            test_client.testing_session = TestingSession
            yield test_client
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def create_user(db, role, email):
    user = User(
        full_name=f"Test {role.value}",
        email=email,
        password_hash=hash_password(PASSWORD),
        role=role,
        is_active=True,
    )
    db.add(user)
    db.flush()
    return user


def login(client, email):
    response = client.get("/login")
    assert response.status_code == 200

    match = re.search(
        r'name="csrf_token"\s+value="([^"]+)"',
        response.text,
    )
    assert match is not None

    response = client.post(
        "/login",
        data={
            "email": email,
            "password": PASSWORD,
            "csrf_token": match.group(1),
        },
    )
    assert response.status_code == 303, response.text


# ----------------------------------------------
# Dashboard test data
# ----------------------------------------------

@pytest.fixture
def dashboard_data(client):
    with client.testing_session() as db:
        admin = create_user(
            db, UserRole.ADMIN, "admin@dashboard.test"
        )
        staff = create_user(
            db, UserRole.STAFF, "staff@dashboard.test"
        )
        attendee = create_user(
            db, UserRole.ATTENDEE, "attendee@dashboard.test"
        )

        venue = Venue(
            name="Dashboard Test Hall",
            location="Colombo",
            capacity=100,
            description="Dashboard tests",
            hourly_hire_rate=Decimal("1000.00"),
            is_open_for_hire=True,
        )
        db.add(venue)
        db.flush()

        start = (
            datetime.now(timezone.utc)
            + timedelta(days=30)
        ).replace(tzinfo=None)

        event = Event(
            title="Dashboard Statistics Test Event",
            category="Workshop",
            description="Dashboard statistics test",
            venue_id=venue.id,
            organiser_id=admin.id,
            start_time=start,
            end_time=start + timedelta(hours=3),
            status=EventStatus.PUBLISHED,
        )
        db.add(event)
        db.flush()

        # Assign the staff member to the event.
        assignment = EventStaffAssignment(
            event_id=event.id,
            staff_user_id=staff.id,
            assigned_by=admin.id,
        )
        db.add(assignment)

        category = TicketCategory(
            event_id=event.id,
            name="General Admission",
            price=Decimal("1500.00"),
            quantity=10,
            sold_count=3,
        )
        db.add(category)
        db.flush()

        booking = Booking(
            user_id=attendee.id,
            event_id=event.id,
            ticket_category_id=category.id,
            quantity=3,
            total_amount=Decimal("4500.00"),
            status=BookingStatus.CONFIRMED,
        )
        db.add(booking)
        db.flush()

        # Three issued tickets:
        # 1 checked in, 1 valid, 1 cancelled.
        for number, ticket_status in enumerate(
            [
                TicketStatus.USED,
                TicketStatus.VALID,
                TicketStatus.CANCELLED,
            ],
            start=1,
        ):
            db.add(
                Ticket(
                    booking_id=booking.id,
                    event_id=event.id,
                    ticket_category_id=category.id,
                    qr_token=f"dashboard-test-token-{number}",
                    status=ticket_status,
                    scan_attempts=0,
                )
            )

        data = {
            "event_title": event.title,
            "event_id": event.id,
            "staff_id": staff.id,
            "admin_id": admin.id,
        }

        db.commit()

    return data


# ----------------------------------------------
# Test 1 — Anonymous access
# ----------------------------------------------

def test_anonymous_cannot_open_staff_dashboard(client):
    response = client.get("/staff/dashboard")
    assert response.status_code == 401


# ----------------------------------------------
# Test 2 — Attendee access
# ----------------------------------------------

def test_attendee_cannot_open_staff_dashboard(
    client, dashboard_data
):
    login(client, "attendee@dashboard.test")

    response = client.get("/staff/dashboard")
    assert response.status_code == 403


# ----------------------------------------------
# Test 3 — Staff access
# ----------------------------------------------

def test_staff_can_open_dashboard(client, dashboard_data):
    login(client, "staff@dashboard.test")

    response = client.get("/staff/dashboard")

    assert response.status_code == 200
    assert "Staff Event Dashboard" in response.text
    assert dashboard_data["event_title"] in response.text


# ----------------------------------------------
# Test 4 — Correct ticket statistics
# ----------------------------------------------

def test_dashboard_displays_correct_statistics(
    client, dashboard_data
):
    login(client, "staff@dashboard.test")

    response = client.get("/staff/dashboard")

    assert response.status_code == 200

    # Three issued tickets, one used, one valid,
    # and one cancelled.
    assert re.search(
        r"Total Tickets</h6>\s*<h2>\s*3\s*</h2>",
        response.text,
    )
    assert re.search(
        r"Checked In</h6>\s*<h2>\s*1\s*</h2>",
        response.text,
    )
    assert re.search(
        r"Remaining Valid</h6>\s*<h2>\s*1\s*</h2>",
        response.text,
    )
    assert "33.3%" in response.text


# ----------------------------------------------
# Test 5 — Published event with zero tickets
# ----------------------------------------------

def test_dashboard_handles_event_with_no_tickets(
    client, dashboard_data
):
    with client.testing_session() as db:
        original_event = db.query(Event).filter_by(
            title="Dashboard Statistics Test Event"
        ).one()

        empty_event = Event(
            title="Empty Dashboard Test Event",
            category="Workshop",
            description="No tickets issued",
            venue_id=original_event.venue_id,
            organiser_id=original_event.organiser_id,
            start_time=original_event.start_time,
            end_time=original_event.end_time,
            status=EventStatus.PUBLISHED,
        )
        db.add(empty_event)
        db.flush()

        # Assign staff to the empty event as well.
        db.add(
            EventStaffAssignment(
                event_id=empty_event.id,
                staff_user_id=dashboard_data["staff_id"],
                assigned_by=dashboard_data["admin_id"],
            )
        )

        db.commit()

    login(client, "staff@dashboard.test")

    response = client.get("/staff/dashboard")

    assert response.status_code == 200
    assert "Empty Dashboard Test Event" in response.text

    # The empty event must show zero progress.
    empty_section = response.text.split(
        "Empty Dashboard Test Event", 1
    )[1].split("</div>\n        </div>", 1)[0]

    assert "0.0%" in empty_section or "0%" in empty_section


# ----------------------------------------------
# Test 6 — Unassigned events are hidden
# ----------------------------------------------

def test_unassigned_event_is_hidden(
    client, dashboard_data
):
    with client.testing_session() as db:
        original_event = db.get(
            Event, dashboard_data["event_id"]
        )

        unassigned_event = Event(
            title="Unassigned Private Event",
            category="Workshop",
            description="Not assigned to current staff",
            venue_id=original_event.venue_id,
            organiser_id=original_event.organiser_id,
            start_time=original_event.start_time,
            end_time=original_event.end_time,
            status=EventStatus.PUBLISHED,
        )
        db.add(unassigned_event)
        db.commit()

    login(client, "staff@dashboard.test")

    response = client.get("/staff/dashboard")

    assert response.status_code == 200
    assert dashboard_data["event_title"] in response.text
    assert "Unassigned Private Event" not in response.text


# ----------------------------------------------
# Test 7 — Staff without assignments
# ----------------------------------------------

def test_staff_without_assignments_sees_no_events(
    client, dashboard_data
):
    with client.testing_session() as db:
        create_user(
            db,
            UserRole.STAFF,
            "unassigned@dashboard.test",
        )
        db.commit()

    login(client, "unassigned@dashboard.test")

    response = client.get("/staff/dashboard")

    assert response.status_code == 200
    assert "Dashboard Statistics Test Event" not in response.text
