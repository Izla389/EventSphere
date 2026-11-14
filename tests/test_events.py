
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.event_validation import (
    EventValidationError,
    check_ticket_capacity,
    check_venue_availability,
    validate_event,
    validate_ticket_category,
)
from app.models.models import (
    Event,
    EventStatus,
    TicketCategory,
    User,
    UserRole,
    Venue,
)


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    Base.metadata.create_all(bind=engine)

    with Session(engine) as session:
        yield session

    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def future_times():
    start = datetime.now(timezone.utc) + timedelta(days=10)
    end = start + timedelta(hours=3)
    return start, end


def make_user(db):
    user = User(
        full_name="Test Admin",
        email="event-admin@example.com",
        password_hash="test-hash",
        role=UserRole.ADMIN,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def make_venue(db, capacity=100):
    venue = Venue(
        name="Test Conference Hall",
        location="Colombo",
        capacity=capacity,
        description="Test venue",
        hourly_hire_rate=1000,
        is_open_for_hire=True,
    )
    db.add(venue)
    db.commit()
    db.refresh(venue)
    return venue


def make_event(db, venue, organiser, start=None, end=None):
    if start is None or end is None:
        start, end = future_times()

    event = Event(
        title="Technology Conference",
        category="Conference",
        venue_id=venue.id,
        organiser_id=organiser.id,
        start_time=start,
        end_time=end,
        description="Test event",
        status=EventStatus.DRAFT,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


# --------------------------------------------
# Event validation tests
# --------------------------------------------

def test_valid_event_information():
    start, end = future_times()

    result = validate_event(
        title="Technology Conference",
        category="Conference",
        start_time=start.isoformat(),
        end_time=end.isoformat(),
        description="A technology event",
        image_url="",
    )

    assert result["title"] == "Technology Conference"
    assert result["category"] == "Conference"


def test_event_end_must_be_after_start():
    start, end = future_times()

    with pytest.raises(EventValidationError):
        validate_event(
            title="Technology Conference",
            category="Conference",
            start_time=end.isoformat(),
            end_time=start.isoformat(),
            description="Test",
            image_url="",
        )


def test_event_start_must_be_in_future():
    start = datetime.now(timezone.utc) - timedelta(days=2)
    end = start + timedelta(hours=2)

    with pytest.raises(EventValidationError):
        validate_event(
            title="Past Event",
            category="Conference",
            start_time=start.isoformat(),
            end_time=end.isoformat(),
            description="Test",
            image_url="",
        )


def test_event_requires_timezone():
    with pytest.raises(EventValidationError):
        validate_event(
            title="Technology Conference",
            category="Conference",
            start_time="2030-01-01T10:00",
            end_time="2030-01-01T12:00",
            description="Test",
            image_url="",
        )


# --------------------------------------------
# Scheduling conflict tests
# --------------------------------------------

def test_overlapping_event_is_rejected(db):
    organiser = make_user(db)
    venue = make_venue(db)
    start, end = future_times()

    make_event(db, venue, organiser, start, end)

    with pytest.raises(EventValidationError):
        check_venue_availability(
            db,
            venue.id,
            start + timedelta(hours=1),
            end + timedelta(hours=1),
        )


def test_non_overlapping_event_is_allowed(db):
    organiser = make_user(db)
    venue = make_venue(db)
    start, end = future_times()

    make_event(db, venue, organiser, start, end)

    check_venue_availability(
        db,
        venue.id,
        end,
        end + timedelta(hours=2),
    )


def test_cancelled_event_does_not_block_venue(db):
    organiser = make_user(db)
    venue = make_venue(db)
    start, end = future_times()

    event = make_event(db, venue, organiser, start, end)
    event.status = EventStatus.CANCELLED
    db.commit()

    check_venue_availability(
        db,
        venue.id,
        start + timedelta(hours=1),
        end,
    )


# --------------------------------------------
# Ticket validation tests
# --------------------------------------------

def test_valid_ticket_category():
    result = validate_ticket_category(
        name="VIP",
        price="3500.00",
        quantity="20",
    )

    assert result["name"] == "VIP"
    assert result["quantity"] == 20
    assert result["price"] == 3500


def test_negative_ticket_price_is_rejected():
    with pytest.raises(EventValidationError):
        validate_ticket_category(
            name="VIP",
            price="-100",
            quantity="20",
        )


def test_negative_ticket_quantity_is_rejected():
    with pytest.raises(EventValidationError):
        validate_ticket_category(
            name="VIP",
            price="1000",
            quantity="-5",
        )


def test_ticket_quantity_cannot_exceed_venue_capacity(db):
    organiser = make_user(db)
    venue = make_venue(db, capacity=100)
    event = make_event(db, venue, organiser)

    db.add(
        TicketCategory(
            event_id=event.id,
            name="General",
            price=1000,
            quantity=80,
            sold_count=0,
        )
    )
    db.commit()

    with pytest.raises(EventValidationError):
        check_ticket_capacity(
            db,
            event.id,
            venue.capacity,
            new_quantity=30,
        )


def test_ticket_quantity_within_capacity_is_allowed(db):
    organiser = make_user(db)
    venue = make_venue(db, capacity=100)
    event = make_event(db, venue, organiser)

    check_ticket_capacity(
        db,
        event.id,
        venue.capacity,
        new_quantity=50,
    )


# ==================================================
# STEP 8.6 - FASTAPI INTEGRATION TESTS
# ==================================================

import re

from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.database import get_db
from app.main import app
from app.security import hash_password


@pytest.fixture
def event_client():
    """Create a separate test database for each API test."""

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine)

    def override_get_db():
        with TestingSession() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    try:
        with TestClient(app, follow_redirects=False) as client:
            client.testing_session = TestingSession
            yield client
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def event_csrf(client, url):
    """Read the CSRF token from an HTML form."""

    response = client.get(url)

    assert response.status_code == 200, response.text

    match = re.search(
        r'name="csrf_token"\s+value="([^"]+)"',
        response.text,
    )

    assert match is not None, "CSRF token not found"

    return match.group(1)


def event_login(client, role=UserRole.ADMIN):
    """Create a test user and log in using Step 6 authentication."""

    email = f"events-{role.value}@example.com"
    password = "StrongPassword123!"

    with client.testing_session() as session:
        session.add(
            User(
                full_name=f"Event Test {role.value}",
                email=email,
                password_hash=hash_password(password),
                role=role,
                is_active=True,
            )
        )
        session.commit()

    csrf = event_csrf(client, "/login")

    response = client.post(
        "/login",
        data={
            "email": email,
            "password": password,
            "csrf_token": csrf,
        },
    )

    assert response.status_code == 303, response.text


def event_create_venue(client, capacity=100):
    """Insert a venue directly into the test database."""

    with client.testing_session() as session:
        venue = Venue(
            name="Event Test Hall",
            location="Colombo",
            capacity=capacity,
            description="Venue for event integration tests",
            hourly_hire_rate=1500,
            is_open_for_hire=True,
        )

        session.add(venue)
        session.commit()
        session.refresh(venue)

        return venue.id


def event_payload(csrf_token, venue_id, **overrides):
    """Build valid event form data."""

    start, end = future_times()

    data = {
        "title": "Technology Conference",
        "category": "Conference",
        "venue_id": str(venue_id),
        "start_time": start.isoformat(),
        "end_time": end.isoformat(),
        "description": "Technology and innovation",
        "image_url": "",
        "csrf_token": csrf_token,
    }

    data.update(overrides)
    return data


def event_create_draft(client, venue_id):
    """Create a draft event through its real FastAPI route."""

    csrf = event_csrf(client, "/admin/events/new")

    response = client.post(
        "/admin/events/new",
        data=event_payload(csrf, venue_id),
    )

    assert response.status_code == 303, response.text

    with client.testing_session() as session:
        event = session.query(Event).one()
        return event.id


def event_add_ticket(
    client,
    event_id,
    name="General Admission",
    price="1500.00",
    quantity="50",
):
    csrf = event_csrf(
        client,
        f"/admin/events/{event_id}/tickets/new",
    )

    return client.post(
        f"/admin/events/{event_id}/tickets/new",
        data={
            "name": name,
            "price": price,
            "quantity": quantity,
            "csrf_token": csrf,
        },
    )


# --------------------------------------------------
# Event creation and viewing
# --------------------------------------------------

def test_admin_can_create_event(event_client):
    event_login(event_client)
    venue_id = event_create_venue(event_client)

    event_id = event_create_draft(event_client, venue_id)

    with event_client.testing_session() as session:
        event = session.get(Event, event_id)

        assert event is not None
        assert event.title == "Technology Conference"
        assert event.status == EventStatus.DRAFT
        assert event.venue_id == venue_id


def test_admin_can_view_event(event_client):
    event_login(event_client)
    venue_id = event_create_venue(event_client)
    event_id = event_create_draft(event_client, venue_id)

    response = event_client.get(
        f"/admin/events/{event_id}"
    )

    assert response.status_code == 200
    assert "Technology Conference" in response.text


def test_admin_can_list_events(event_client):
    event_login(event_client)
    venue_id = event_create_venue(event_client)
    event_create_draft(event_client, venue_id)

    response = event_client.get("/admin/events/")

    assert response.status_code == 200
    assert "Technology Conference" in response.text


# --------------------------------------------------
# Event editing
# --------------------------------------------------

def test_admin_can_edit_draft_event(event_client):
    event_login(event_client)
    venue_id = event_create_venue(event_client)
    event_id = event_create_draft(event_client, venue_id)

    csrf = event_csrf(
        event_client,
        f"/admin/events/{event_id}/edit",
    )

    response = event_client.post(
        f"/admin/events/{event_id}/edit",
        data=event_payload(
            csrf,
            venue_id,
            title="Updated Technology Conference",
        ),
    )

    assert response.status_code == 303, response.text

    with event_client.testing_session() as session:
        event = session.get(Event, event_id)

        assert event.title == "Updated Technology Conference"


def test_admin_can_delete_draft_event(event_client):
    event_login(event_client)
    venue_id = event_create_venue(event_client)
    event_id = event_create_draft(event_client, venue_id)

    csrf = event_csrf(
        event_client,
        f"/admin/events/{event_id}",
    )

    response = event_client.post(
        f"/admin/events/{event_id}/delete",
        data={"csrf_token": csrf},
    )

    assert response.status_code == 303

    with event_client.testing_session() as session:
        assert session.get(Event, event_id) is None


# --------------------------------------------------
# Ticket categories
# --------------------------------------------------

def test_admin_can_add_ticket_category(event_client):
    event_login(event_client)
    venue_id = event_create_venue(event_client)
    event_id = event_create_draft(event_client, venue_id)

    response = event_add_ticket(event_client, event_id)

    assert response.status_code == 303, response.text

    with event_client.testing_session() as session:
        ticket = session.query(TicketCategory).one()

        assert ticket.name == "General Admission"
        assert ticket.quantity == 50
        assert ticket.sold_count == 0


def test_admin_can_edit_ticket_category(event_client):
    event_login(event_client)
    venue_id = event_create_venue(event_client)
    event_id = event_create_draft(event_client, venue_id)

    event_add_ticket(event_client, event_id)

    with event_client.testing_session() as session:
        ticket_id = session.query(TicketCategory).one().id

    csrf = event_csrf(
        event_client,
        f"/admin/events/{event_id}/tickets/{ticket_id}/edit",
    )

    response = event_client.post(
        f"/admin/events/{event_id}/tickets/{ticket_id}/edit",
        data={
            "name": "VIP",
            "price": "3500.00",
            "quantity": "20",
            "csrf_token": csrf,
        },
    )

    assert response.status_code == 303, response.text

    with event_client.testing_session() as session:
        ticket = session.get(TicketCategory, ticket_id)

        assert ticket.name == "VIP"
        assert ticket.quantity == 20


def test_admin_can_delete_ticket_category(event_client):
    event_login(event_client)
    venue_id = event_create_venue(event_client)
    event_id = event_create_draft(event_client, venue_id)

    event_add_ticket(event_client, event_id)

    with event_client.testing_session() as session:
        ticket_id = session.query(TicketCategory).one().id

    csrf = event_csrf(
        event_client,
        f"/admin/events/{event_id}",
    )

    response = event_client.post(
        f"/admin/events/{event_id}/tickets/{ticket_id}/delete",
        data={"csrf_token": csrf},
    )

    assert response.status_code == 303

    with event_client.testing_session() as session:
        assert session.get(TicketCategory, ticket_id) is None


# --------------------------------------------------
# Venue capacity
# --------------------------------------------------

def test_ticket_capacity_exceeded_via_route(event_client):
    event_login(event_client)
    venue_id = event_create_venue(event_client, capacity=60)
    event_id = event_create_draft(event_client, venue_id)

    first = event_add_ticket(
        event_client,
        event_id,
        name="General",
        quantity="50",
    )

    assert first.status_code == 303

    second = event_add_ticket(
        event_client,
        event_id,
        name="VIP",
        quantity="20",
    )

    assert second.status_code == 400

    with event_client.testing_session() as session:
        assert session.query(TicketCategory).count() == 1


# --------------------------------------------------
# Scheduling conflicts
# --------------------------------------------------

def test_overlapping_event_rejected_via_route(event_client):
    event_login(event_client)
    venue_id = event_create_venue(event_client)

    event_create_draft(event_client, venue_id)

    csrf = event_csrf(
        event_client,
        "/admin/events/new",
    )

    response = event_client.post(
        "/admin/events/new",
        data=event_payload(csrf, venue_id),
    )

    assert response.status_code == 400
    assert "already has an event" in response.text

    with event_client.testing_session() as session:
        assert session.query(Event).count() == 1


# --------------------------------------------------
# Publishing and cancellation
# --------------------------------------------------

def test_admin_can_publish_event(event_client):
    event_login(event_client)
    venue_id = event_create_venue(event_client)
    event_id = event_create_draft(event_client, venue_id)

    event_add_ticket(event_client, event_id)

    csrf = event_csrf(
        event_client,
        f"/admin/events/{event_id}",
    )

    response = event_client.post(
        f"/admin/events/{event_id}/publish",
        data={"csrf_token": csrf},
    )

    assert response.status_code == 303

    with event_client.testing_session() as session:
        event = session.get(Event, event_id)
        assert event.status == EventStatus.PUBLISHED


def test_cannot_publish_without_tickets(event_client):
    event_login(event_client)
    venue_id = event_create_venue(event_client)
    event_id = event_create_draft(event_client, venue_id)

    csrf = event_csrf(
        event_client,
        f"/admin/events/{event_id}",
    )

    response = event_client.post(
        f"/admin/events/{event_id}/publish",
        data={"csrf_token": csrf},
    )

    assert response.status_code == 409


def test_admin_can_cancel_event(event_client):
    event_login(event_client)
    venue_id = event_create_venue(event_client)
    event_id = event_create_draft(event_client, venue_id)

    event_add_ticket(event_client, event_id)

    csrf = event_csrf(
        event_client,
        f"/admin/events/{event_id}",
    )

    publish_response = event_client.post(
        f"/admin/events/{event_id}/publish",
        data={"csrf_token": csrf},
    )

    assert publish_response.status_code == 303

    csrf = event_csrf(
        event_client,
        f"/admin/events/{event_id}",
    )

    response = event_client.post(
        f"/admin/events/{event_id}/cancel",
        data={"csrf_token": csrf},
    )

    assert response.status_code == 303

    with event_client.testing_session() as session:
        event = session.get(Event, event_id)
        assert event.status == EventStatus.CANCELLED


def test_published_event_cannot_be_edited(event_client):
    event_login(event_client)
    venue_id = event_create_venue(event_client)
    event_id = event_create_draft(event_client, venue_id)

    event_add_ticket(event_client, event_id)

    csrf = event_csrf(
        event_client,
        f"/admin/events/{event_id}",
    )

    event_client.post(
        f"/admin/events/{event_id}/publish",
        data={"csrf_token": csrf},
    )

    response = event_client.get(
        f"/admin/events/{event_id}/edit",
    )

    assert response.status_code == 409


# --------------------------------------------------
# Role-based access
# --------------------------------------------------

def test_attendee_cannot_manage_events(event_client):
    event_login(event_client, UserRole.ATTENDEE)

    response = event_client.get("/admin/events/")
    assert response.status_code == 403

    response = event_client.get("/admin/events/new")
    assert response.status_code == 403


def test_staff_cannot_manage_events(event_client):
    event_login(event_client, UserRole.STAFF)

    response = event_client.get("/admin/events/")
    assert response.status_code == 403


def test_anonymous_user_cannot_manage_events(event_client):
    response = event_client.get("/admin/events/")

    assert response.status_code == 401


# --------------------------------------------------
# CSRF protection
# --------------------------------------------------

def test_csrf_required_for_event_creation(event_client):
    event_login(event_client)
    venue_id = event_create_venue(event_client)

    response = event_client.post(
        "/admin/events/new",
        data=event_payload(
            "invalid-token",
            venue_id,
        ),
    )

    assert response.status_code == 403

    with event_client.testing_session() as session:
        assert session.query(Event).count() == 0


def test_csrf_required_for_event_publishing(event_client):
    event_login(event_client)
    venue_id = event_create_venue(event_client)
    event_id = event_create_draft(event_client, venue_id)

    event_add_ticket(event_client, event_id)

    response = event_client.post(
        f"/admin/events/{event_id}/publish",
        data={"csrf_token": "invalid-token"},
    )

    assert response.status_code == 403

    with event_client.testing_session() as session:
        event = session.get(Event, event_id)
        assert event.status == EventStatus.DRAFT
