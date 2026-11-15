
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
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


@pytest.fixture
def ticket_data(client):
    with client.testing_session() as db:
        admin = create_user(
            db,
            UserRole.ADMIN,
            "admin@checkin.test",
        )

        staff = create_user(
            db,
            UserRole.STAFF,
            "staff@checkin.test",
        )

        attendee = create_user(
            db,
            UserRole.ATTENDEE,
            "attendee@checkin.test",
        )

        venue = Venue(
            name="Check-In Route Test Hall",
            location="Colombo",
            capacity=100,
            description="Route security tests",
            hourly_hire_rate=Decimal("1000.00"),
            is_open_for_hire=True,
        )

        db.add(venue)
        db.flush()

        start_time = (
            datetime.now(timezone.utc)
            + timedelta(days=30)
        ).replace(tzinfo=None)

        event = Event(
            title="Staff Check-In Test Event",
            category="Workshop",
            description="Check-in route tests",
            venue_id=venue.id,
            organiser_id=admin.id,
            start_time=start_time,
            end_time=start_time + timedelta(hours=3),
            status=EventStatus.PUBLISHED,
        )

        db.add(event)
        db.flush()

        # Assign staff to this event.
        db.add(
            EventStaffAssignment(
                event_id=event.id,
                staff_user_id=staff.id,
                assigned_by=admin.id,
            )
        )

        category = TicketCategory(
            event_id=event.id,
            name="General Admission",
            price=Decimal("1500.00"),
            quantity=10,
            sold_count=1,
        )

        db.add(category)
        db.flush()

        booking = Booking(
            user_id=attendee.id,
            event_id=event.id,
            ticket_category_id=category.id,
            quantity=1,
            total_amount=Decimal("1500.00"),
            status=BookingStatus.CONFIRMED,
        )

        db.add(booking)
        db.flush()

        ticket = Ticket(
            booking_id=booking.id,
            event_id=event.id,
            ticket_category_id=category.id,
            qr_token="route-test-qr-token-123",
            status=TicketStatus.VALID,
            scan_attempts=0,
        )

        db.add(ticket)
        db.flush()

        data = {
            "event_id": event.id,
            "ticket_id": ticket.id,
            "staff_id": staff.id,
            "admin_id": admin.id,
            "qr_token": ticket.qr_token,
        }

        db.commit()

    return data


# ----------------------------------------------
# Authentication and CSRF helpers
# ----------------------------------------------

def get_csrf(client, url):
    response = client.get(url)

    assert response.status_code == 200, response.text

    match = re.search(
        r'name="csrf_token"\s+value="([^"]+)"',
        response.text,
    )

    assert match is not None, (
        f"CSRF token not found on {url}"
    )

    return match.group(1)


def login(client, email):
    csrf = get_csrf(client, "/login")

    response = client.post(
        "/login",
        data={
            "email": email,
            "password": PASSWORD,
            "csrf_token": csrf,
        },
    )

    assert response.status_code == 303, response.text


def submit_checkin(
    client,
    ticket_data,
    csrf_token=None,
):
    if csrf_token is None:
        csrf_token = get_csrf(
            client,
            "/staff/checkin/",
        )

    return client.post(
        "/staff/checkin/",
        data={
            "event_id": str(ticket_data["event_id"]),
            "qr_token": ticket_data["qr_token"],
            "csrf_token": csrf_token,
        },
    )


def get_ticket(client, ticket_id):
    with client.testing_session() as db:
        return db.get(Ticket, ticket_id)


# ----------------------------------------------
# Test 1 — Anonymous GET access
# ----------------------------------------------

def test_anonymous_cannot_open_checkin_page(client):
    response = client.get("/staff/checkin/")

    assert response.status_code == 401


# ----------------------------------------------
# Test 2 — Attendee GET access
# ----------------------------------------------

def test_attendee_cannot_open_checkin_page(
    client,
    ticket_data,
):
    login(client, "attendee@checkin.test")

    response = client.get("/staff/checkin/")

    assert response.status_code == 403


# ----------------------------------------------
# Test 3 — Staff GET access
# ----------------------------------------------

def test_staff_can_open_checkin_page(
    client,
    ticket_data,
):
    login(client, "staff@checkin.test")

    response = client.get("/staff/checkin/")

    assert response.status_code == 200
    assert "Staff Ticket Check-In" in response.text
    assert "Staff Check-In Test Event" in response.text


# ----------------------------------------------
# Test 4 — Invalid CSRF
# ----------------------------------------------

def test_invalid_csrf_rejects_checkin(
    client,
    ticket_data,
):
    login(client, "staff@checkin.test")

    response = submit_checkin(
        client,
        ticket_data,
        csrf_token="invalid-token",
    )

    assert response.status_code == 403

    ticket = get_ticket(
        client,
        ticket_data["ticket_id"],
    )

    assert ticket.status == TicketStatus.VALID


# ----------------------------------------------
# Test 5 — Successful check-in
# ----------------------------------------------

def test_valid_ticket_can_be_checked_in(
    client,
    ticket_data,
):
    login(client, "staff@checkin.test")

    response = submit_checkin(
        client,
        ticket_data,
    )

    assert response.status_code == 200
    assert "checked in successfully" in response.text

    ticket = get_ticket(
        client,
        ticket_data["ticket_id"],
    )

    assert ticket.status == TicketStatus.USED
    assert ticket.checked_in_at is not None
    assert ticket.checked_in_by == ticket_data["staff_id"]
    assert ticket.scan_attempts == 1


# ----------------------------------------------
# Test 6 — Duplicate check-in
# ----------------------------------------------

def test_duplicate_checkin_is_rejected(
    client,
    ticket_data,
):
    login(client, "staff@checkin.test")

    first = submit_checkin(
        client,
        ticket_data,
    )

    second = submit_checkin(
        client,
        ticket_data,
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert "already been checked in" in second.text

    ticket = get_ticket(
        client,
        ticket_data["ticket_id"],
    )

    assert ticket.status == TicketStatus.USED


# ----------------------------------------------
# Test 7 — Invalid QR token
# ----------------------------------------------

def test_invalid_qr_token_is_rejected(
    client,
    ticket_data,
):
    login(client, "staff@checkin.test")

    csrf = get_csrf(
        client,
        "/staff/checkin/",
    )

    response = client.post(
        "/staff/checkin/",
        data={
            "event_id": str(ticket_data["event_id"]),
            "qr_token": "nonexistent-token",
            "csrf_token": csrf,
        },
    )

    assert response.status_code == 200
    assert "Invalid QR ticket" in response.text


# ----------------------------------------------
# Test 8 — Anonymous POST access
# ----------------------------------------------

def test_anonymous_cannot_submit_checkin(
    client,
    ticket_data,
):
    response = client.post(
        "/staff/checkin/",
        data={
            "event_id": str(ticket_data["event_id"]),
            "qr_token": ticket_data["qr_token"],
            "csrf_token": "invalid-token",
        },
    )

    assert response.status_code == 401


# ----------------------------------------------
# Test 9 — Attendee POST access
# ----------------------------------------------

def test_attendee_cannot_submit_checkin(
    client,
    ticket_data,
):
    login(client, "attendee@checkin.test")

    csrf = get_csrf(client, "/login")

    response = client.post(
        "/staff/checkin/",
        data={
            "event_id": str(ticket_data["event_id"]),
            "qr_token": ticket_data["qr_token"],
            "csrf_token": csrf,
        },
    )

    assert response.status_code == 403

    ticket = get_ticket(
        client,
        ticket_data["ticket_id"],
    )

    assert ticket.status == TicketStatus.VALID


# ----------------------------------------------
# Test 10 — Duplicate scans are counted
# ----------------------------------------------

def test_duplicate_scan_increases_attempt_count(
    client,
    ticket_data,
):
    login(client, "staff@checkin.test")

    first = submit_checkin(client, ticket_data)
    assert first.status_code == 200

    second = submit_checkin(client, ticket_data)
    assert second.status_code == 200
    assert "already been checked in" in second.text

    ticket = get_ticket(
        client,
        ticket_data["ticket_id"],
    )

    assert ticket.status == TicketStatus.USED
    assert ticket.scan_attempts == 2
    assert ticket.checked_in_by == ticket_data["staff_id"]
    assert ticket.checked_in_at is not None


# ----------------------------------------------
# Test 11 — Wrong-event scans are counted
# ----------------------------------------------

def test_wrong_event_scan_increases_attempt_count(
    client,
    ticket_data,
):
    login(client, "staff@checkin.test")

    # Create another published event using the same
    # venue and organiser as the original event.
    with client.testing_session() as db:
        original_event = db.get(
            Event,
            ticket_data["event_id"],
        )

        other_event = Event(
            title="Another Check-In Test Event",
            category="Workshop",
            description="Wrong-event scan test",
            venue_id=original_event.venue_id,
            organiser_id=original_event.organiser_id,
            start_time=original_event.start_time,
            end_time=original_event.end_time,
            status=EventStatus.PUBLISHED,
        )

        db.add(other_event)
        db.flush()

        # Assign staff to the second event so the
        # wrong-event ticket validation can run.
        db.add(
            EventStaffAssignment(
                event_id=other_event.id,
                staff_user_id=ticket_data["staff_id"],
                assigned_by=ticket_data["admin_id"],
            )
        )

        other_event_id = other_event.id
        db.commit()

    csrf = get_csrf(client, "/staff/checkin/")

    response = client.post(
        "/staff/checkin/",
        data={
            "event_id": str(other_event_id),
            "qr_token": ticket_data["qr_token"],
            "csrf_token": csrf,
        },
    )

    assert response.status_code == 200
    assert "belongs to another event" in response.text

    ticket = get_ticket(
        client,
        ticket_data["ticket_id"],
    )

    assert ticket.status == TicketStatus.VALID
    assert ticket.scan_attempts == 1
    assert ticket.checked_in_at is None
    assert ticket.checked_in_by is None


# ----------------------------------------------
# Test 12 — Unassigned staff cannot check in
# ----------------------------------------------

def test_unassigned_staff_cannot_check_in(
    client,
    ticket_data,
):
    with client.testing_session() as db:
        create_user(
            db,
            UserRole.STAFF,
            "unassigned@checkin.test",
        )
        db.commit()

    login(client, "unassigned@checkin.test")

    response = submit_checkin(client, ticket_data)

    assert response.status_code == 200
    assert "not assigned to this event" in response.text

    ticket = get_ticket(
        client,
        ticket_data["ticket_id"],
    )

    assert ticket.status == TicketStatus.VALID
    assert ticket.scan_attempts == 0
    assert ticket.checked_in_at is None
    assert ticket.checked_in_by is None


# ----------------------------------------------
# Test 13 — Removed assignment blocks check-in
# ----------------------------------------------

def test_removed_assignment_blocks_checkin_route(
    client,
    ticket_data,
):
    with client.testing_session() as db:
        assignment = db.scalar(
            select(EventStaffAssignment).where(
                EventStaffAssignment.event_id
                == ticket_data["event_id"],
                EventStaffAssignment.staff_user_id
                == ticket_data["staff_id"],
            )
        )

        assert assignment is not None

        db.delete(assignment)
        db.commit()

    login(client, "staff@checkin.test")

    response = submit_checkin(client, ticket_data)

    assert response.status_code == 200
    assert "not assigned to this event" in response.text

    ticket = get_ticket(
        client,
        ticket_data["ticket_id"],
    )

    assert ticket.status == TicketStatus.VALID
    assert ticket.scan_attempts == 0
    assert ticket.checked_in_at is None
    assert ticket.checked_in_by is None
