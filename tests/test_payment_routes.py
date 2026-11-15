
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
    EventStatus,
    Payment,
    Ticket,
    TicketCategory,
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
def event_data(client):
    with client.testing_session() as db:
        admin = create_user(
            db,
            UserRole.ADMIN,
            "admin@example.com",
        )

        attendee = create_user(
            db,
            UserRole.ATTENDEE,
            "attendee@example.com",
        )

        second_attendee = create_user(
            db,
            UserRole.ATTENDEE,
            "second@example.com",
        )

        venue = Venue(
            name="Payment Test Hall",
            location="Colombo",
            capacity=100,
            description="Payment route tests",
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
            title="Payment Security Test Event",
            category="Workshop",
            description="Security testing",
            venue_id=venue.id,
            organiser_id=admin.id,
            start_time=start_time,
            end_time=start_time + timedelta(hours=3),
            status=EventStatus.PUBLISHED,
        )

        db.add(event)
        db.flush()

        category = TicketCategory(
            event_id=event.id,
            name="General Admission",
            price=Decimal("1500.00"),
            quantity=10,
            sold_count=0,
        )

        db.add(category)
        db.flush()

        data = {
            "event_id": event.id,
            "category_id": category.id,
            "attendee_id": attendee.id,
            "second_attendee_id": second_attendee.id,
        }

        db.commit()

    return data


# ----------------------------------------------
# Authentication helpers
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


def logout_session(client):
    client.cookies.clear()


def create_pending_booking(client, event_data):
    csrf = get_csrf(
        client,
        f"/events/{event_data['event_id']}/book",
    )

    response = client.post(
        f"/events/{event_data['event_id']}/book",
        data={
            "ticket_category_id": str(
                event_data["category_id"]
            ),
            "quantity": "2",
            "csrf_token": csrf,
        },
    )

    assert response.status_code == 303, response.text

    with client.testing_session() as db:
        booking = db.scalar(
            select(Booking).order_by(
                Booking.id.desc()
            )
        )

        assert booking is not None
        return booking.id


def pay_booking(client, booking_id, csrf=None):
    if csrf is None:
        csrf = get_csrf(
            client,
            f"/my-bookings/{booking_id}",
        )

    return client.post(
        f"/my-bookings/{booking_id}/pay",
        data={"csrf_token": csrf},
    )


def get_ticket_ids(client, booking_id):
    with client.testing_session() as db:
        return db.scalars(
            select(Ticket.id)
            .where(Ticket.booking_id == booking_id)
            .order_by(Ticket.id)
        ).all()


def qr_url(booking_id, ticket_id):
    return (
        f"/my-bookings/{booking_id}"
        f"/tickets/{ticket_id}/qr"
    )


# ----------------------------------------------
# Test 1 — Successful payment
# ----------------------------------------------

def test_payment_confirms_booking_and_redirects(
    client,
    event_data,
):
    login(client, "attendee@example.com")

    booking_id = create_pending_booking(
        client,
        event_data,
    )

    response = pay_booking(client, booking_id)

    assert response.status_code == 303
    assert response.headers["location"] == (
        f"/my-bookings/{booking_id}"
    )

    with client.testing_session() as db:
        booking = db.get(Booking, booking_id)

        payments = db.scalars(
            select(Payment).where(
                Payment.booking_id == booking_id
            )
        ).all()

        tickets = db.scalars(
            select(Ticket).where(
                Ticket.booking_id == booking_id
            )
        ).all()

        assert booking.status == BookingStatus.CONFIRMED
        assert len(payments) == 1
        assert len(tickets) == 2

    detail = client.get(
        f"/my-bookings/{booking_id}"
    )

    assert detail.status_code == 200
    assert "Your Tickets" in detail.text


# ----------------------------------------------
# Test 2 — Anonymous payment rejected
# ----------------------------------------------

def test_anonymous_user_cannot_pay(
    client,
    event_data,
):
    login(client, "attendee@example.com")

    booking_id = create_pending_booking(
        client,
        event_data,
    )

    logout_session(client)

    response = client.post(
        f"/my-bookings/{booking_id}/pay",
        data={"csrf_token": "invalid"},
    )

    assert response.status_code == 401

    with client.testing_session() as db:
        booking = db.get(Booking, booking_id)
        assert booking.status == BookingStatus.PENDING


# ----------------------------------------------
# Test 3 — Another attendee cannot pay
# ----------------------------------------------

def test_attendee_cannot_pay_another_users_booking(
    client,
    event_data,
):
    login(client, "attendee@example.com")

    booking_id = create_pending_booking(
        client,
        event_data,
    )

    logout_session(client)
    login(client, "second@example.com")

    # Obtain a valid CSRF token from a page
    # accessible to the second attendee.
    csrf = get_csrf(client, "/login")

    response = pay_booking(
        client,
        booking_id,
        csrf=csrf,
    )

    assert response.status_code == 409

    with client.testing_session() as db:
        booking = db.get(Booking, booking_id)
        assert booking.status == BookingStatus.PENDING


# ----------------------------------------------
# Test 4 — Invalid CSRF rejected
# ----------------------------------------------

def test_invalid_csrf_cannot_confirm_payment(
    client,
    event_data,
):
    login(client, "attendee@example.com")

    booking_id = create_pending_booking(
        client,
        event_data,
    )

    response = pay_booking(
        client,
        booking_id,
        csrf="invalid-token",
    )

    assert response.status_code == 403

    with client.testing_session() as db:
        booking = db.get(Booking, booking_id)
        assert booking.status == BookingStatus.PENDING


# ----------------------------------------------
# Test 5 — Duplicate payment rejected
# ----------------------------------------------

def test_duplicate_payment_is_rejected(
    client,
    event_data,
):
    login(client, "attendee@example.com")

    booking_id = create_pending_booking(
        client,
        event_data,
    )

    csrf = get_csrf(
        client,
        f"/my-bookings/{booking_id}",
    )

    first = pay_booking(
        client,
        booking_id,
        csrf=csrf,
    )

    second = pay_booking(
        client,
        booking_id,
        csrf=csrf,
    )

    assert first.status_code == 303
    assert second.status_code == 409

    assert len(get_ticket_ids(client, booking_id)) == 2


# ----------------------------------------------
# Test 6 — Cancelled booking cannot be paid
# ----------------------------------------------

def test_cancelled_booking_cannot_be_paid(
    client,
    event_data,
):
    login(client, "attendee@example.com")

    booking_id = create_pending_booking(
        client,
        event_data,
    )

    csrf = get_csrf(
        client,
        f"/my-bookings/{booking_id}",
    )

    cancelled = client.post(
        f"/my-bookings/{booking_id}/cancel",
        data={"csrf_token": csrf},
    )

    assert cancelled.status_code == 303

    payment = pay_booking(
        client,
        booking_id,
        csrf=csrf,
    )

    assert payment.status_code == 409

    with client.testing_session() as db:
        booking = db.get(Booking, booking_id)
        assert booking.status == BookingStatus.CANCELLED

    assert get_ticket_ids(client, booking_id) == []


# ----------------------------------------------
# Test 7 — Owner can view QR image
# ----------------------------------------------

def test_ticket_owner_can_view_qr_code(
    client,
    event_data,
):
    login(client, "attendee@example.com")

    booking_id = create_pending_booking(
        client,
        event_data,
    )

    assert pay_booking(
        client,
        booking_id,
    ).status_code == 303

    ticket_id = get_ticket_ids(
        client,
        booking_id,
    )[0]

    response = client.get(
        qr_url(booking_id, ticket_id)
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(
        bytes.fromhex("89504E470D0A1A0A")
    )
    assert "no-store" in response.headers["cache-control"]


# ----------------------------------------------
# Test 8 — Anonymous QR access rejected
# ----------------------------------------------

def test_anonymous_user_cannot_view_qr(
    client,
    event_data,
):
    login(client, "attendee@example.com")

    booking_id = create_pending_booking(
        client,
        event_data,
    )

    assert pay_booking(
        client,
        booking_id,
    ).status_code == 303

    ticket_id = get_ticket_ids(
        client,
        booking_id,
    )[0]

    logout_session(client)

    response = client.get(
        qr_url(booking_id, ticket_id)
    )

    assert response.status_code == 401


# ----------------------------------------------
# Test 9 — Another attendee cannot view QR
# ----------------------------------------------

def test_other_attendee_cannot_view_qr(
    client,
    event_data,
):
    login(client, "attendee@example.com")

    booking_id = create_pending_booking(
        client,
        event_data,
    )

    assert pay_booking(
        client,
        booking_id,
    ).status_code == 303

    ticket_id = get_ticket_ids(
        client,
        booking_id,
    )[0]

    logout_session(client)
    login(client, "second@example.com")

    response = client.get(
        qr_url(booking_id, ticket_id)
    )

    assert response.status_code == 404


# ----------------------------------------------
# Test 10 — Pending booking has no QR access
# ----------------------------------------------

def test_pending_booking_cannot_show_qr(
    client,
    event_data,
):
    login(client, "attendee@example.com")

    booking_id = create_pending_booking(
        client,
        event_data,
    )

    response = client.get(
        qr_url(booking_id, 99999)
    )

    assert response.status_code == 404


# ----------------------------------------------
# Test 11 — Cancelled booking has no QR access
# ----------------------------------------------

def test_cancelled_booking_cannot_show_qr(
    client,
    event_data,
):
    login(client, "attendee@example.com")

    booking_id = create_pending_booking(
        client,
        event_data,
    )

    csrf = get_csrf(
        client,
        f"/my-bookings/{booking_id}",
    )

    cancelled = client.post(
        f"/my-bookings/{booking_id}/cancel",
        data={"csrf_token": csrf},
    )

    assert cancelled.status_code == 303

    response = client.get(
        qr_url(booking_id, 99999)
    )

    assert response.status_code == 404


# ----------------------------------------------
# Test 12 — Invalid ticket ID rejected
# ----------------------------------------------

def test_invalid_ticket_id_is_rejected(
    client,
    event_data,
):
    login(client, "attendee@example.com")

    booking_id = create_pending_booking(
        client,
        event_data,
    )

    assert pay_booking(
        client,
        booking_id,
    ).status_code == 303

    response = client.get(
        qr_url(booking_id, 99999)
    )

    assert response.status_code == 404
