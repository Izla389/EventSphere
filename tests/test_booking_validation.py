
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.booking_validation import (
    BookingValidationError,
    calculate_booking_total,
    check_ticket_availability,
    get_available_tickets,
    reserve_booking,
    validate_booking_quantity,
    validate_event_bookable,
)
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


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    Base.metadata.create_all(bind=engine)

    try:
        with Session(engine) as session:
            yield session
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture
def booking_data(db):
    attendee = User(
        full_name="Test Attendee",
        email="booking-attendee@example.com",
        password_hash="test-hash",
        role=UserRole.ATTENDEE,
        is_active=True,
    )

    admin = User(
        full_name="Test Administrator",
        email="booking-admin@example.com",
        password_hash="test-hash",
        role=UserRole.ADMIN,
        is_active=True,
    )

    db.add_all([attendee, admin])
    db.flush()

    venue = Venue(
        name="Booking Test Hall",
        location="Colombo",
        capacity=100,
        description="Test venue",
        hourly_hire_rate=Decimal("1000.00"),
        is_open_for_hire=True,
    )

    db.add(venue)
    db.flush()

    event = Event(
        title="Booking Test Conference",
        category="Conference",
        venue_id=venue.id,
        organiser_id=admin.id,
        start_time=datetime.now(timezone.utc)
        + timedelta(days=10),
        end_time=datetime.now(timezone.utc)
        + timedelta(days=10, hours=3),
        description="Test event",
        status=EventStatus.PUBLISHED,
    )

    db.add(event)
    db.flush()

    category = TicketCategory(
        event_id=event.id,
        name="General Admission",
        price=Decimal("1500.00"),
        quantity=100,
        sold_count=20,
    )

    db.add(category)
    db.commit()

    return {
        "attendee_id": attendee.id,
        "event_id": event.id,
        "category_id": category.id,
    }


# ---------------------------------------------
# Quantity validation
# ---------------------------------------------

def test_valid_booking_quantity():
    assert validate_booking_quantity("3") == 3


def test_maximum_booking_quantity_allowed():
    assert validate_booking_quantity("10") == 10


def test_zero_booking_quantity_rejected():
    with pytest.raises(BookingValidationError):
        validate_booking_quantity("0")


def test_negative_booking_quantity_rejected():
    with pytest.raises(BookingValidationError):
        validate_booking_quantity("-2")


def test_more_than_ten_tickets_rejected():
    with pytest.raises(BookingValidationError):
        validate_booking_quantity("11")


def test_decimal_booking_quantity_rejected():
    with pytest.raises(BookingValidationError):
        validate_booking_quantity("2.5")


def test_boolean_booking_quantity_rejected():
    with pytest.raises(BookingValidationError):
        validate_booking_quantity(True)


# ---------------------------------------------
# Price calculations
# ---------------------------------------------

def test_booking_total_calculation():
    total = calculate_booking_total(
        Decimal("1500.00"),
        "3",
    )

    assert total == Decimal("4500.00")


def test_free_ticket_total():
    total = calculate_booking_total(
        Decimal("0.00"),
        2,
    )

    assert total == Decimal("0.00")


def test_decimal_precision():
    total = calculate_booking_total(
        Decimal("19.99"),
        3,
    )

    assert total == Decimal("59.97")


def test_negative_ticket_price_rejected():
    with pytest.raises(BookingValidationError):
        calculate_booking_total(
            Decimal("-100.00"),
            2,
        )


def test_invalid_ticket_price_rejected():
    with pytest.raises(BookingValidationError):
        calculate_booking_total(
            "not-a-price",
            2,
        )


# ---------------------------------------------
# Event eligibility
# ---------------------------------------------

def test_published_future_event_is_bookable(
    db, booking_data
):
    event = db.get(
        Event,
        booking_data["event_id"],
    )

    validate_event_bookable(event)


def test_draft_event_not_bookable(
    db, booking_data
):
    event = db.get(
        Event,
        booking_data["event_id"],
    )

    event.status = EventStatus.DRAFT

    with pytest.raises(BookingValidationError):
        validate_event_bookable(event)


def test_cancelled_event_not_bookable(
    db, booking_data
):
    event = db.get(
        Event,
        booking_data["event_id"],
    )

    event.status = EventStatus.CANCELLED

    with pytest.raises(BookingValidationError):
        validate_event_bookable(event)


def test_started_event_not_bookable(
    db, booking_data
):
    event = db.get(
        Event,
        booking_data["event_id"],
    )

    event.start_time = (
        datetime.now(timezone.utc)
        - timedelta(hours=1)
    )

    with pytest.raises(BookingValidationError):
        validate_event_bookable(event)


# ---------------------------------------------
# Ticket availability
# ---------------------------------------------

def test_available_ticket_count(
    db, booking_data
):
    category = db.get(
        TicketCategory,
        booking_data["category_id"],
    )

    assert get_available_tickets(category) == 80


def test_booking_within_available_quantity(
    db, booking_data
):
    category = db.get(
        TicketCategory,
        booking_data["category_id"],
    )

    assert check_ticket_availability(
        category, 5
    ) == 5


def test_sold_out_category_rejected(
    db, booking_data
):
    category = db.get(
        TicketCategory,
        booking_data["category_id"],
    )

    category.sold_count = category.quantity

    with pytest.raises(BookingValidationError):
        check_ticket_availability(
            category, 1
        )


def test_insufficient_tickets_rejected(
    db, booking_data
):
    category = db.get(
        TicketCategory,
        booking_data["category_id"],
    )

    category.sold_count = 98

    with pytest.raises(BookingValidationError):
        check_ticket_availability(
            category, 3
        )


# ---------------------------------------------
# Booking reservation
# ---------------------------------------------

def test_reserve_booking_creates_pending_booking(
    db, booking_data
):
    booking = reserve_booking(
        db,
        user_id=booking_data["attendee_id"],
        event_id=booking_data["event_id"],
        ticket_category_id=booking_data["category_id"],
        quantity=3,
    )

    db.commit()

    assert booking.id is not None
    assert booking.status == BookingStatus.PENDING
    assert booking.quantity == 3
    assert booking.total_amount == Decimal("4500.00")

    saved = db.get(Booking, booking.id)

    assert saved is not None


def test_reservation_updates_inventory(
    db, booking_data
):
    reserve_booking(
        db,
        user_id=booking_data["attendee_id"],
        event_id=booking_data["event_id"],
        ticket_category_id=booking_data["category_id"],
        quantity=4,
    )

    db.commit()

    category = db.get(
        TicketCategory,
        booking_data["category_id"],
    )

    assert category.sold_count == 24
    assert get_available_tickets(category) == 76


def test_failed_reservation_does_not_change_inventory(
    db, booking_data
):
    category = db.get(
        TicketCategory,
        booking_data["category_id"],
    )

    with pytest.raises(BookingValidationError):
        reserve_booking(
            db,
            user_id=booking_data["attendee_id"],
            event_id=booking_data["event_id"],
            ticket_category_id=booking_data["category_id"],
            quantity=100,
        )

    db.rollback()
    db.refresh(category)

    assert category.sold_count == 20
    assert db.query(Booking).count() == 0


def test_transaction_rollback_releases_inventory(
    db, booking_data
):
    reserve_booking(
        db,
        user_id=booking_data["attendee_id"],
        event_id=booking_data["event_id"],
        ticket_category_id=booking_data["category_id"],
        quantity=5,
    )

    db.rollback()

    category = db.get(
        TicketCategory,
        booking_data["category_id"],
    )

    assert category.sold_count == 20
    assert db.query(Booking).count() == 0


def test_category_must_belong_to_event(
    db, booking_data
):
    other_event = Event(
        title="Another Conference",
        category="Conference",
        venue_id=db.query(Venue).first().id,
        organiser_id=db.query(User).filter(
            User.role == UserRole.ADMIN
        ).first().id,
        start_time=datetime.now(timezone.utc)
        + timedelta(days=20),
        end_time=datetime.now(timezone.utc)
        + timedelta(days=20, hours=2),
        status=EventStatus.PUBLISHED,
    )

    db.add(other_event)
    db.flush()

    with pytest.raises(BookingValidationError):
        reserve_booking(
            db,
            user_id=booking_data["attendee_id"],
            event_id=other_event.id,
            ticket_category_id=booking_data["category_id"],
            quantity=2,
        )

    db.rollback()


def test_reservation_does_not_commit_automatically(
    db, booking_data
):
    reserve_booking(
        db,
        user_id=booking_data["attendee_id"],
        event_id=booking_data["event_id"],
        ticket_category_id=booking_data["category_id"],
        quantity=2,
    )

    assert db.in_transaction()

    db.rollback()

    assert db.query(Booking).count() == 0
