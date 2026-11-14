
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
    TicketCategory,
    User,
    UserRole,
    Venue,
)
from app.security import hash_password


PASSWORD = "StrongPassword123!"


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
            name="Test Conference Hall",
            location="Colombo",
            capacity=100,
            description="Test venue",
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
            title="Step 9 Test Event",
            category="Workshop",
            description="Automated booking tests",
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
            quantity=5,
            sold_count=0,
        )

        db.add(category)
        db.flush()

        result = {
            "event_id": event.id,
            "category_id": category.id,
            "attendee_id": attendee.id,
            "second_attendee_id": second_attendee.id,
        }

        db.commit()

    return result


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
    # Clear the signed session cookie between test users.
    client.cookies.clear()


def make_booking(
    client,
    event_id,
    category_id,
    quantity="2",
    csrf_token=None,
):
    if csrf_token is None:
        csrf_token = get_csrf(
            client,
            f"/events/{event_id}/book",
        )

    return client.post(
        f"/events/{event_id}/book",
        data={
            "ticket_category_id": str(category_id),
            "quantity": quantity,
            "csrf_token": csrf_token,
        },
    )


def get_inventory(client, category_id):
    with client.testing_session() as db:
        category = db.get(TicketCategory, category_id)
        return category.sold_count


def get_bookings(client):
    with client.testing_session() as db:
        return db.scalars(
            select(Booking).order_by(Booking.id)
        ).all()


# ----------------------------------------------
# Public browsing
# ----------------------------------------------

def test_public_can_browse_events(client, event_data):
    response = client.get("/events/")

    assert response.status_code == 200
    assert "Step 9 Test Event" in response.text


def test_public_can_view_event(client, event_data):
    response = client.get(
        f"/events/{event_data['event_id']}"
    )

    assert response.status_code == 200
    assert "General Admission" in response.text
    assert "1500.00" in response.text


def test_draft_event_is_not_public(client, event_data):
    with client.testing_session() as db:
        event = db.get(Event, event_data["event_id"])
        event.status = EventStatus.DRAFT
        db.commit()

    response = client.get(
        f"/events/{event_data['event_id']}"
    )

    assert response.status_code == 404


# ----------------------------------------------
# Authentication and permissions
# ----------------------------------------------

def test_anonymous_cannot_open_booking_form(
    client,
    event_data,
):
    response = client.get(
        f"/events/{event_data['event_id']}/book"
    )

    assert response.status_code == 401


def test_admin_cannot_book(client, event_data):
    login(client, "admin@example.com")

    response = client.get(
        f"/events/{event_data['event_id']}/book"
    )

    assert response.status_code == 403


def test_attendee_can_open_booking_form(
    client,
    event_data,
):
    login(client, "attendee@example.com")

    response = client.get(
        f"/events/{event_data['event_id']}/book"
    )

    assert response.status_code == 200
    assert "Reserve Tickets" in response.text


def test_anonymous_cannot_view_booking_history(
    client,
    event_data,
):
    response = client.get("/my-bookings/")

    assert response.status_code == 401


def test_admin_cannot_view_attendee_bookings(
    client,
    event_data,
):
    login(client, "admin@example.com")

    response = client.get("/my-bookings/")

    assert response.status_code == 403


# ----------------------------------------------
# Booking creation and inventory
# ----------------------------------------------

def test_valid_booking_creates_pending_reservation(
    client,
    event_data,
):
    login(client, "attendee@example.com")

    response = make_booking(
        client,
        event_data["event_id"],
        event_data["category_id"],
        quantity="3",
    )

    assert response.status_code == 303

    bookings = get_bookings(client)

    assert len(bookings) == 1

    booking = bookings[0]

    assert booking.status == BookingStatus.PENDING
    assert booking.quantity == 3
    assert booking.total_amount == Decimal("4500.00")
    assert booking.user_id == event_data["attendee_id"]
    assert booking.booking_reference

    assert get_inventory(
        client,
        event_data["category_id"],
    ) == 3


@pytest.mark.parametrize(
    "quantity",
    ["0", "-1", "11", "2.5", "abc"],
)
def test_invalid_quantities_are_rejected(
    client,
    event_data,
    quantity,
):
    login(client, "attendee@example.com")

    response = make_booking(
        client,
        event_data["event_id"],
        event_data["category_id"],
        quantity=quantity,
    )

    assert response.status_code == 400
    assert len(get_bookings(client)) == 0

    assert get_inventory(
        client,
        event_data["category_id"],
    ) == 0


def test_cannot_book_more_than_available(
    client,
    event_data,
):
    login(client, "attendee@example.com")

    response = make_booking(
        client,
        event_data["event_id"],
        event_data["category_id"],
        quantity="6",
    )

    assert response.status_code == 400
    assert len(get_bookings(client)) == 0
    assert get_inventory(
        client,
        event_data["category_id"],
    ) == 0


def test_sold_out_category_cannot_be_booked(
    client,
    event_data,
):
    with client.testing_session() as db:
        category = db.get(
            TicketCategory,
            event_data["category_id"],
        )
        category.sold_count = category.quantity
        db.commit()

    login(client, "attendee@example.com")

    response = make_booking(
        client,
        event_data["event_id"],
        event_data["category_id"],
        quantity="1",
    )

    assert response.status_code == 400
    assert len(get_bookings(client)) == 0
    assert get_inventory(
        client,
        event_data["category_id"],
    ) == 5


def test_cancelled_event_cannot_be_booked(
    client,
    event_data,
):
    with client.testing_session() as db:
        event = db.get(Event, event_data["event_id"])
        event.status = EventStatus.CANCELLED
        db.commit()

    login(client, "attendee@example.com")

    # The booking form must not be accessible.
    response = client.get(
        f"/events/{event_data['event_id']}/book"
    )

    assert response.status_code == 404
    assert len(get_bookings(client)) == 0


# ----------------------------------------------
# CSRF protection
# ----------------------------------------------

def test_invalid_csrf_rejects_booking(
    client,
    event_data,
):
    login(client, "attendee@example.com")

    response = make_booking(
        client,
        event_data["event_id"],
        event_data["category_id"],
        quantity="2",
        csrf_token="invalid-token",
    )

    assert response.status_code == 403
    assert len(get_bookings(client)) == 0
    assert get_inventory(
        client,
        event_data["category_id"],
    ) == 0


def test_missing_csrf_rejects_booking(
    client,
    event_data,
):
    login(client, "attendee@example.com")

    response = client.post(
        f"/events/{event_data['event_id']}/book",
        data={
            "ticket_category_id": str(
                event_data["category_id"]
            ),
            "quantity": "2",
        },
    )

    assert response.status_code in (403, 422)
    assert len(get_bookings(client)) == 0
    assert get_inventory(
        client,
        event_data["category_id"],
    ) == 0


# ----------------------------------------------
# Booking history and ownership
# ----------------------------------------------

def test_attendee_can_view_own_booking(
    client,
    event_data,
):
    login(client, "attendee@example.com")

    response = make_booking(
        client,
        event_data["event_id"],
        event_data["category_id"],
    )

    assert response.status_code == 303

    booking = get_bookings(client)[0]

    history = client.get("/my-bookings/")
    detail = client.get(
        f"/my-bookings/{booking.id}"
    )

    assert history.status_code == 200
    assert detail.status_code == 200
    assert booking.booking_reference in detail.text


def test_attendee_cannot_view_another_booking(
    client,
    event_data,
):
    login(client, "attendee@example.com")

    response = make_booking(
        client,
        event_data["event_id"],
        event_data["category_id"],
    )

    assert response.status_code == 303

    booking_id = get_bookings(client)[0].id

    logout_session(client)
    login(client, "second@example.com")

    response = client.get(
        f"/my-bookings/{booking_id}"
    )

    assert response.status_code == 404


# ----------------------------------------------
# Pending booking cancellation
# ----------------------------------------------

def test_cancel_pending_booking_releases_inventory(
    client,
    event_data,
):
    login(client, "attendee@example.com")

    response = make_booking(
        client,
        event_data["event_id"],
        event_data["category_id"],
        quantity="3",
    )

    assert response.status_code == 303

    booking_id = get_bookings(client)[0].id

    assert get_inventory(
        client,
        event_data["category_id"],
    ) == 3

    csrf = get_csrf(
        client,
        f"/my-bookings/{booking_id}",
    )

    response = client.post(
        f"/my-bookings/{booking_id}/cancel",
        data={"csrf_token": csrf},
    )

    assert response.status_code == 303

    booking = get_bookings(client)[0]

    assert booking.status == BookingStatus.CANCELLED
    assert booking.cancelled_at is not None

    assert get_inventory(
        client,
        event_data["category_id"],
    ) == 0


def test_cannot_cancel_same_booking_twice(
    client,
    event_data,
):
    login(client, "attendee@example.com")

    make_booking(
        client,
        event_data["event_id"],
        event_data["category_id"],
        quantity="2",
    )

    booking_id = get_bookings(client)[0].id

    csrf = get_csrf(
        client,
        f"/my-bookings/{booking_id}",
    )

    url = f"/my-bookings/{booking_id}/cancel"

    first = client.post(
        url,
        data={"csrf_token": csrf},
    )

    second = client.post(
        url,
        data={"csrf_token": csrf},
    )

    assert first.status_code == 303
    assert second.status_code == 409

    assert get_inventory(
        client,
        event_data["category_id"],
    ) == 0


def test_cannot_cancel_another_users_booking(
    client,
    event_data,
):
    login(client, "attendee@example.com")

    make_booking(
        client,
        event_data["event_id"],
        event_data["category_id"],
        quantity="2",
    )

    booking_id = get_bookings(client)[0].id

    logout_session(client)
    login(client, "second@example.com")

    csrf = get_csrf(client, "/login")

    response = client.post(
        f"/my-bookings/{booking_id}/cancel",
        data={"csrf_token": csrf},
    )

    assert response.status_code == 404

    assert get_inventory(
        client,
        event_data["category_id"],
    ) == 2

    assert (
        get_bookings(client)[0].status
        == BookingStatus.PENDING
    )


def test_invalid_csrf_rejects_cancellation(
    client,
    event_data,
):
    login(client, "attendee@example.com")

    make_booking(
        client,
        event_data["event_id"],
        event_data["category_id"],
        quantity="2",
    )

    booking_id = get_bookings(client)[0].id

    response = client.post(
        f"/my-bookings/{booking_id}/cancel",
        data={"csrf_token": "invalid-token"},
    )

    assert response.status_code == 403

    assert get_inventory(
        client,
        event_data["category_id"],
    ) == 2

    assert (
        get_bookings(client)[0].status
        == BookingStatus.PENDING
    )

# ----------------------------------------------
# Step 9.7.7 — Additional booking edge cases
# ----------------------------------------------


def test_direct_post_cannot_book_cancelled_event(
    client,
    event_data,
):
    login(client, "attendee@example.com")

    # Obtain a valid CSRF token before cancelling.
    csrf = get_csrf(
        client,
        f"/events/{event_data['event_id']}/book",
    )

    with client.testing_session() as db:
        event = db.get(Event, event_data["event_id"])
        event.status = EventStatus.CANCELLED
        db.commit()

    response = make_booking(
        client,
        event_data["event_id"],
        event_data["category_id"],
        quantity="1",
        csrf_token=csrf,
    )

    assert response.status_code in (400, 404, 409)
    assert len(get_bookings(client)) == 0

    assert get_inventory(
        client,
        event_data["category_id"],
    ) == 0


def test_direct_post_cannot_book_past_event(
    client,
    event_data,
):
    login(client, "attendee@example.com")

    csrf = get_csrf(
        client,
        f"/events/{event_data['event_id']}/book",
    )

    with client.testing_session() as db:
        event = db.get(Event, event_data["event_id"])

        past_start = (
            datetime.now(timezone.utc)
            - timedelta(days=1)
        ).replace(tzinfo=None)

        event.start_time = past_start
        event.end_time = past_start + timedelta(hours=2)

        db.commit()

    response = make_booking(
        client,
        event_data["event_id"],
        event_data["category_id"],
        quantity="1",
        csrf_token=csrf,
    )

    assert response.status_code in (400, 409)
    assert len(get_bookings(client)) == 0

    assert get_inventory(
        client,
        event_data["category_id"],
    ) == 0


def test_direct_post_cannot_book_draft_event(
    client,
    event_data,
):
    login(client, "attendee@example.com")

    csrf = get_csrf(
        client,
        f"/events/{event_data['event_id']}/book",
    )

    with client.testing_session() as db:
        event = db.get(Event, event_data["event_id"])
        event.status = EventStatus.DRAFT
        db.commit()

    response = make_booking(
        client,
        event_data["event_id"],
        event_data["category_id"],
        quantity="1",
        csrf_token=csrf,
    )

    assert response.status_code in (400, 404, 409)
    assert len(get_bookings(client)) == 0

    assert get_inventory(
        client,
        event_data["category_id"],
    ) == 0


def test_cannot_book_category_from_another_event(
    client,
    event_data,
):
    login(client, "attendee@example.com")

    csrf = get_csrf(
        client,
        f"/events/{event_data['event_id']}/book",
    )

    with client.testing_session() as db:
        original_event = db.get(
            Event,
            event_data["event_id"],
        )

        other_event = Event(
            title="Another Test Event",
            category="Conference",
            description="Different event",
            venue_id=original_event.venue_id,
            organiser_id=original_event.organiser_id,
            start_time=original_event.start_time
            + timedelta(days=5),
            end_time=original_event.end_time
            + timedelta(days=5),
            status=EventStatus.PUBLISHED,
        )

        db.add(other_event)
        db.flush()

        other_category = TicketCategory(
            event_id=other_event.id,
            name="Other Event Ticket",
            price=Decimal("2000.00"),
            quantity=10,
            sold_count=0,
        )

        db.add(other_category)
        db.flush()

        other_category_id = other_category.id

        db.commit()

    # Request the original event, but submit a ticket
    # category belonging to a different event.
    response = make_booking(
        client,
        event_data["event_id"],
        other_category_id,
        quantity="1",
        csrf_token=csrf,
    )

    assert response.status_code == 400
    assert len(get_bookings(client)) == 0

    assert get_inventory(
        client,
        event_data["category_id"],
    ) == 0

    assert get_inventory(
        client,
        other_category_id,
    ) == 0


def test_anonymous_direct_post_cannot_create_booking(
    client,
    event_data,
):
    response = client.post(
        f"/events/{event_data['event_id']}/book",
        data={
            "ticket_category_id": str(
                event_data["category_id"]
            ),
            "quantity": "1",
            "csrf_token": "invalid-token",
        },
    )

    assert response.status_code == 401
    assert len(get_bookings(client)) == 0

    assert get_inventory(
        client,
        event_data["category_id"],
    ) == 0
