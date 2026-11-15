
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.checkin_service import (
    CheckInValidationError,
    check_in_ticket,
)
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


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    Base.metadata.create_all(bind=engine)

    SessionLocal = sessionmaker(
        bind=engine,
        expire_on_commit=False,
    )

    try:
        with SessionLocal() as session:
            yield session
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture
def sample_data(db):
    admin = User(
        full_name="Test Admin",
        email="admin@checkin.test",
        password_hash="test-hash",
        role=UserRole.ADMIN,
        is_active=True,
    )

    staff = User(
        full_name="Test Staff",
        email="staff@checkin.test",
        password_hash="test-hash",
        role=UserRole.STAFF,
        is_active=True,
    )

    attendee = User(
        full_name="Test Attendee",
        email="attendee@checkin.test",
        password_hash="test-hash",
        role=UserRole.ATTENDEE,
        is_active=True,
    )

    db.add_all([admin, staff, attendee])
    db.flush()

    venue = Venue(
        name="Check-In Test Hall",
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
        title="Check-In Test Event",
        category="Workshop",
        description="Check-in tests",
        venue_id=venue.id,
        organiser_id=admin.id,
        start_time=start_time,
        end_time=start_time + timedelta(hours=3),
        status=EventStatus.PUBLISHED,
    )

    db.add(event)
    db.flush()

    # Assign the staff member to the event.
    db.add(
        EventStaffAssignment(
            event_id=event.id,
            staff_user_id=staff.id,
            assigned_by=admin.id,
        )
    )

    category = TicketCategory(
        event_id=event.id,
        name="General",
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
        qr_token="test-qr-token-123",
        status=TicketStatus.VALID,
        scan_attempts=0,
    )

    db.add(ticket)
    db.commit()

    return {
        "staff_id": staff.id,
        "admin_id": admin.id,
        "attendee_id": attendee.id,
        "event_id": event.id,
        "booking_id": booking.id,
        "ticket_id": ticket.id,
        "qr_token": ticket.qr_token,
    }


def perform_checkin(db, sample_data, **overrides):
    arguments = {
        "qr_token": sample_data["qr_token"],
        "event_id": sample_data["event_id"],
        "staff_user_id": sample_data["staff_id"],
    }

    arguments.update(overrides)

    return check_in_ticket(db, **arguments)


# ----------------------------------------------
# Existing validation tests
# ----------------------------------------------

def test_valid_ticket_can_be_checked_in(db, sample_data):
    ticket = perform_checkin(db, sample_data)
    db.commit()

    assert ticket.status == TicketStatus.USED
    assert ticket.checked_in_at is not None
    assert ticket.checked_in_by == sample_data["staff_id"]
    assert ticket.scan_attempts == 1


def test_duplicate_checkin_is_rejected(db, sample_data):
    perform_checkin(db, sample_data)
    db.commit()

    with pytest.raises(
        CheckInValidationError,
        match="already been checked in",
    ):
        perform_checkin(db, sample_data)

    db.rollback()

    ticket = db.get(Ticket, sample_data["ticket_id"])

    assert ticket.status == TicketStatus.USED


def test_attendee_cannot_check_in_ticket(db, sample_data):
    with pytest.raises(
        CheckInValidationError,
        match="not authorized",
    ):
        perform_checkin(
            db,
            sample_data,
            staff_user_id=sample_data["attendee_id"],
        )

    db.rollback()

    ticket = db.get(Ticket, sample_data["ticket_id"])
    assert ticket.status == TicketStatus.VALID


def test_invalid_qr_token_is_rejected(db, sample_data):
    with pytest.raises(
        CheckInValidationError,
        match="Invalid QR ticket",
    ):
        perform_checkin(
            db,
            sample_data,
            qr_token="nonexistent-token",
        )

    db.rollback()


def test_wrong_event_is_rejected(db, sample_data):
    with pytest.raises(
        CheckInValidationError,
        match="Event not found",
    ):
        perform_checkin(
            db,
            sample_data,
            event_id=sample_data["event_id"] + 1,
        )

    db.rollback()


def test_cancelled_ticket_is_rejected(db, sample_data):
    ticket = db.get(Ticket, sample_data["ticket_id"])
    ticket.status = TicketStatus.CANCELLED
    db.commit()

    with pytest.raises(
        CheckInValidationError,
        match="cancelled",
    ):
        perform_checkin(db, sample_data)

    db.rollback()


def test_unconfirmed_booking_is_rejected(db, sample_data):
    booking = db.get(
        Booking,
        sample_data["booking_id"],
    )
    booking.status = BookingStatus.PENDING
    db.commit()

    with pytest.raises(
        CheckInValidationError,
        match="not confirmed",
    ):
        perform_checkin(db, sample_data)

    db.rollback()


def test_admin_can_check_in_ticket(db, sample_data):
    ticket = perform_checkin(
        db,
        sample_data,
        staff_user_id=sample_data["admin_id"],
    )
    db.commit()

    assert ticket.status == TicketStatus.USED
    assert ticket.checked_in_by == sample_data["admin_id"]


# ----------------------------------------------
# New event-assignment security tests
# ----------------------------------------------

def test_unassigned_staff_cannot_check_in_ticket(
    db, sample_data
):
    unassigned_staff = User(
        full_name="Unassigned Staff",
        email="unassigned@checkin.test",
        password_hash="test-hash",
        role=UserRole.STAFF,
        is_active=True,
    )
    db.add(unassigned_staff)
    db.commit()

    with pytest.raises(
        CheckInValidationError,
        match="not assigned to this event",
    ) as error:
        perform_checkin(
            db,
            sample_data,
            staff_user_id=unassigned_staff.id,
        )

    assert error.value.save_scan_attempt is False

    db.rollback()

    ticket = db.get(Ticket, sample_data["ticket_id"])
    assert ticket.status == TicketStatus.VALID
    assert ticket.scan_attempts == 0
    assert ticket.checked_in_by is None


def test_removed_assignment_blocks_checkin(
    db, sample_data
):
    assignment = db.query(EventStaffAssignment).filter_by(
        event_id=sample_data["event_id"],
        staff_user_id=sample_data["staff_id"],
    ).one()

    db.delete(assignment)
    db.commit()

    with pytest.raises(
        CheckInValidationError,
        match="not assigned to this event",
    ):
        perform_checkin(db, sample_data)

    db.rollback()

    ticket = db.get(Ticket, sample_data["ticket_id"])
    assert ticket.status == TicketStatus.VALID
    assert ticket.scan_attempts == 0


def test_assignment_to_different_event_does_not_allow_checkin(
    db, sample_data
):
    original_event = db.get(
        Event, sample_data["event_id"]
    )

    other_event = Event(
        title="Another Assigned Event",
        category="Workshop",
        description="Assignment isolation test",
        venue_id=original_event.venue_id,
        organiser_id=original_event.organiser_id,
        start_time=original_event.start_time,
        end_time=original_event.end_time,
        status=EventStatus.PUBLISHED,
    )
    db.add(other_event)
    db.flush()

    other_staff = User(
        full_name="Other Event Staff",
        email="otherstaff@checkin.test",
        password_hash="test-hash",
        role=UserRole.STAFF,
        is_active=True,
    )
    db.add(other_staff)
    db.flush()

    db.add(
        EventStaffAssignment(
            event_id=other_event.id,
            staff_user_id=other_staff.id,
            assigned_by=sample_data["admin_id"],
        )
    )
    db.commit()

    with pytest.raises(
        CheckInValidationError,
        match="not assigned to this event",
    ):
        perform_checkin(
            db,
            sample_data,
            staff_user_id=other_staff.id,
        )

    db.rollback()

    ticket = db.get(Ticket, sample_data["ticket_id"])
    assert ticket.status == TicketStatus.VALID
    assert ticket.scan_attempts == 0
