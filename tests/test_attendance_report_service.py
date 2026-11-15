
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.attendance_report_service import (
    get_event_attendance_report,
    get_all_event_attendance_reports,
)
from app.models.models import (
    Booking,
    BookingStatus,
    Event,
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

    TestingSession = sessionmaker(
        bind=engine,
        expire_on_commit=False,
    )

    try:
        with TestingSession() as session:
            yield session
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture
def sample_event(db):
    admin = User(
        full_name="Report Admin",
        email="report-admin@test.com",
        password_hash="test-hash",
        role=UserRole.ADMIN,
        is_active=True,
    )

    attendee = User(
        full_name="Report Attendee",
        email="report-attendee@test.com",
        password_hash="test-hash",
        role=UserRole.ATTENDEE,
        is_active=True,
    )

    db.add_all([admin, attendee])
    db.flush()

    venue = Venue(
        name="Report Test Hall",
        location="Colombo",
        capacity=100,
        description="Attendance report tests",
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
        title="Attendance Report Test Event",
        category="Workshop",
        description="Attendance reporting tests",
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
        quantity=100,
        sold_count=4,
    )

    db.add(category)
    db.flush()

    booking = Booking(
        user_id=attendee.id,
        event_id=event.id,
        ticket_category_id=category.id,
        quantity=4,
        total_amount=Decimal("6000.00"),
        status=BookingStatus.CONFIRMED,
    )

    db.add(booking)
    db.flush()

    # Two checked-in tickets and two valid tickets.
    for number in range(4):
        ticket = Ticket(
            booking_id=booking.id,
            event_id=event.id,
            ticket_category_id=category.id,
            qr_token=f"report-test-token-{number}",
            status=(
                TicketStatus.USED
                if number < 2
                else TicketStatus.VALID
            ),
            scan_attempts=1 if number < 2 else 0,
        )
        db.add(ticket)

    db.commit()

    return {
        "event_id": event.id,
        "booking_id": booking.id,
        "attendee_id": attendee.id,
        "venue_id": venue.id,
        "admin_id": admin.id,
    }


# ----------------------------------------------
# Test 1 — Correct attendance totals
# ----------------------------------------------

def test_report_calculates_ticket_totals(
    db,
    sample_event,
):
    report = get_event_attendance_report(
        db,
        sample_event["event_id"],
    )

    assert report is not None
    assert report["total_tickets"] == 4
    assert report["checked_in"] == 2
    assert report["remaining"] == 2


# ----------------------------------------------
# Test 2 — Correct attendance percentage
# ----------------------------------------------

def test_report_calculates_percentage(
    db,
    sample_event,
):
    report = get_event_attendance_report(
        db,
        sample_event["event_id"],
    )

    assert report["attendance_percentage"] == 50.0


# ----------------------------------------------
# Test 3 — Correct event information
# ----------------------------------------------

def test_report_contains_event_information(
    db,
    sample_event,
):
    report = get_event_attendance_report(
        db,
        sample_event["event_id"],
    )

    assert report["event_title"] == (
        "Attendance Report Test Event"
    )
    assert report["event_status"] == "published"
    assert report["venue_name"] == "Report Test Hall"
    assert report["event_id"] == sample_event["event_id"]


# ----------------------------------------------
# Test 4 — Unknown event
# ----------------------------------------------

def test_unknown_event_returns_none(db):
    report = get_event_attendance_report(
        db,
        999999,
    )

    assert report is None


# ----------------------------------------------
# Test 5 — All event reports
# ----------------------------------------------

def test_get_all_event_reports(
    db,
    sample_event,
):
    reports = get_all_event_attendance_reports(db)

    assert len(reports) == 1
    assert reports[0]["event_id"] == (
        sample_event["event_id"]
    )
    assert reports[0]["total_tickets"] == 4


# ----------------------------------------------
# Test 6 — Event with no tickets
# ----------------------------------------------

def test_event_without_tickets(
    db,
    sample_event,
):
    original_event = db.get(
        Event,
        sample_event["event_id"],
    )

    empty_event = Event(
        title="Empty Attendance Event",
        category="Workshop",
        description="Event without bookings",
        venue_id=sample_event["venue_id"],
        organiser_id=sample_event["admin_id"],
        start_time=original_event.start_time,
        end_time=original_event.end_time,
        status=EventStatus.PUBLISHED,
    )

    db.add(empty_event)
    db.commit()

    report = get_event_attendance_report(
        db,
        empty_event.id,
    )

    assert report["total_tickets"] == 0
    assert report["checked_in"] == 0
    assert report["remaining"] == 0
    assert report["attendance_percentage"] == 0.0


# ----------------------------------------------
# Test 7 — Cancelled tickets excluded
# ----------------------------------------------

def test_cancelled_tickets_are_excluded(
    db,
    sample_event,
):
    ticket = (
        db.query(Ticket)
        .filter(
            Ticket.event_id == sample_event["event_id"],
            Ticket.status == TicketStatus.VALID,
        )
        .first()
    )

    ticket.status = TicketStatus.CANCELLED
    db.commit()

    report = get_event_attendance_report(
        db,
        sample_event["event_id"],
    )

    assert report["total_tickets"] == 3
    assert report["checked_in"] == 2
    assert report["remaining"] == 1
    assert report["attendance_percentage"] == pytest.approx(
        66.67,
        abs=0.01,
    )


# ----------------------------------------------
# Test 8 — Unconfirmed bookings excluded
# ----------------------------------------------

def test_unconfirmed_bookings_are_excluded(
    db,
    sample_event,
):
    booking = db.get(
        Booking,
        sample_event["booking_id"],
    )

    booking.status = BookingStatus.PENDING
    db.commit()

    report = get_event_attendance_report(
        db,
        sample_event["event_id"],
    )

    assert report["total_tickets"] == 0
    assert report["checked_in"] == 0
    assert report["remaining"] == 0
    assert report["attendance_percentage"] == 0.0
