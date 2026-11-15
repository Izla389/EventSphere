
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from app.models.models import (
    Booking,
    BookingStatus,
    Event,
    EventStatus,
    Payment,
    TicketStatus,
)
from app.payment_service import (
    PaymentValidationError,
    confirm_simulated_payment,
)


# ---------------------------------------
# Test helper functions
# ---------------------------------------

def make_booking(
    *,
    status=BookingStatus.PENDING,
    user_id=1,
    quantity=2,
    total_amount=Decimal("3000.00"),
):
    return Booking(
        id=10,
        user_id=user_id,
        event_id=20,
        ticket_category_id=30,
        quantity=quantity,
        total_amount=total_amount,
        status=status,
    )


def make_future_event(event_id=20):
    start = datetime.now(timezone.utc) + timedelta(days=30)

    return Event(
        id=event_id,
        status=EventStatus.PUBLISHED,
        start_time=start,
        end_time=start + timedelta(hours=2),
    )


def make_mock_db(booking):
    db = MagicMock()

    db.scalar.side_effect = [
        booking.event_id,
        make_future_event(booking.event_id),
        booking,
    ]

    return db


# ---------------------------------------
# Existing payment validation tests
# ---------------------------------------

def test_cancelled_booking_cannot_be_paid():
    booking = make_booking(
        status=BookingStatus.CANCELLED
    )
    db = make_mock_db(booking)

    with pytest.raises(
        PaymentValidationError,
        match="Cancelled bookings cannot be paid",
    ):
        confirm_simulated_payment(
            db,
            booking_id=booking.id,
            user_id=booking.user_id,
        )


def test_confirmed_booking_cannot_be_paid_again():
    booking = make_booking(
        status=BookingStatus.CONFIRMED
    )
    db = make_mock_db(booking)

    with pytest.raises(
        PaymentValidationError,
        match="already been confirmed",
    ):
        confirm_simulated_payment(
            db,
            booking_id=booking.id,
            user_id=booking.user_id,
        )


def test_attendee_cannot_pay_for_another_booking():
    booking = make_booking(user_id=1)
    db = make_mock_db(booking)

    with pytest.raises(
        PaymentValidationError,
        match="another attendee",
    ):
        confirm_simulated_payment(
            db,
            booking_id=booking.id,
            user_id=999,
        )


def test_invalid_booking_quantity_is_rejected():
    booking = make_booking(quantity=0)
    db = make_mock_db(booking)

    with pytest.raises(
        PaymentValidationError,
        match="Invalid booking quantity",
    ):
        confirm_simulated_payment(
            db,
            booking_id=booking.id,
            user_id=booking.user_id,
        )


def test_negative_payment_amount_is_rejected():
    booking = make_booking(
        total_amount=Decimal("-100.00")
    )
    db = make_mock_db(booking)

    with pytest.raises(
        PaymentValidationError,
        match="Invalid payment amount",
    ):
        confirm_simulated_payment(
            db,
            booking_id=booking.id,
            user_id=booking.user_id,
        )


def test_missing_booking_is_rejected():
    db = MagicMock()
    db.scalar.return_value = None

    with pytest.raises(
        PaymentValidationError,
        match="Booking not found",
    ):
        confirm_simulated_payment(
            db,
            booking_id=999,
            user_id=1,
        )


def test_existing_payment_is_rejected():
    booking = make_booking()
    db = make_mock_db(booking)

    db.scalar.side_effect = [
        booking.event_id,
        make_future_event(booking.event_id),
        booking,
        Payment(id=1, booking_id=booking.id),
    ]

    with pytest.raises(
        PaymentValidationError,
        match="A payment already exists",
    ):
        confirm_simulated_payment(
            db,
            booking_id=booking.id,
            user_id=booking.user_id,
        )


def test_successful_payment_creates_correct_tickets():
    booking = make_booking(quantity=3)
    db = make_mock_db(booking)

    db.scalar.side_effect = [
        booking.event_id,
        make_future_event(booking.event_id),
        booking,
        None,
        None,
    ]

    payment, updated_booking, tickets = (
        confirm_simulated_payment(
            db,
            booking_id=booking.id,
            user_id=booking.user_id,
        )
    )

    assert payment.booking_id == booking.id
    assert payment.amount == Decimal("3000.00")

    assert updated_booking.status == BookingStatus.CONFIRMED

    assert len(tickets) == 3

    tokens = [ticket.qr_token for ticket in tickets]
    assert len(set(tokens)) == 3

    assert all(
        ticket.status == TicketStatus.VALID
        for ticket in tickets
    )

    assert db.flush.called
    assert not db.commit.called


# ---------------------------------------
# Step 10.4 — Event validation tests
# ---------------------------------------

def test_cancelled_event_cannot_be_paid():
    booking = make_booking()
    db = MagicMock()

    event = make_future_event(booking.event_id)
    event.status = EventStatus.CANCELLED

    db.scalar.side_effect = [
        booking.event_id,
        event,
    ]

    with pytest.raises(
        PaymentValidationError,
        match="not available for payment",
    ):
        confirm_simulated_payment(
            db,
            booking_id=booking.id,
            user_id=booking.user_id,
        )

    assert not db.flush.called


def test_draft_event_cannot_be_paid():
    booking = make_booking()
    db = MagicMock()

    event = make_future_event(booking.event_id)
    event.status = EventStatus.DRAFT

    db.scalar.side_effect = [
        booking.event_id,
        event,
    ]

    with pytest.raises(
        PaymentValidationError,
        match="not available for payment",
    ):
        confirm_simulated_payment(
            db,
            booking_id=booking.id,
            user_id=booking.user_id,
        )

    assert not db.flush.called


def test_started_event_cannot_be_paid():
    booking = make_booking()
    db = MagicMock()

    event = make_future_event(booking.event_id)

    event.start_time = (
        datetime.now(timezone.utc) - timedelta(hours=1)
    )

    db.scalar.side_effect = [
        booking.event_id,
        event,
    ]

    with pytest.raises(
        PaymentValidationError,
        match="event has started",
    ):
        confirm_simulated_payment(
            db,
            booking_id=booking.id,
            user_id=booking.user_id,
        )

    assert not db.flush.called
