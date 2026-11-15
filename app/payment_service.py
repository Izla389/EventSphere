
import secrets
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.models import (
    Booking,
    BookingStatus,
    Event,
    EventStatus,
    Payment,
    PaymentStatus,
    Ticket,
    TicketStatus,
)


class PaymentValidationError(Exception):
    """Raised when payment confirmation is not allowed."""


def confirm_simulated_payment(
    db: Session,
    *,
    booking_id: int,
    user_id: int,
):
    """
    Confirm a simulated payment and generate tickets.

    The caller is responsible for committing the transaction.
    """

    # ---------------------------------------
    # 1. Find the event ID for this booking
    # ---------------------------------------

    event_id = db.scalar(
        select(Booking.event_id).where(
            Booking.id == booking_id
        )
    )

    if event_id is None:
        raise PaymentValidationError(
            "Booking not found."
        )

    # ---------------------------------------
    # 2. Lock the event
    # ---------------------------------------

    # Lock the event first to maintain the
    # same lock order as the booking service.
    event = db.scalar(
        select(Event)
        .where(Event.id == event_id)
        .with_for_update()
    )

    if event is None:
        raise PaymentValidationError(
            "Event not found."
        )

    # ---------------------------------------
    # 3. Validate event status
    # ---------------------------------------

    if event.status != EventStatus.PUBLISHED:
        raise PaymentValidationError(
            "This event is not available for payment."
        )

    # ---------------------------------------
    # 4. Validate event start time
    # ---------------------------------------

    now = datetime.now(timezone.utc)

    event_start = event.start_time

    if event_start is None:
        raise PaymentValidationError(
            "Event start time is missing."
        )

    # Treat timezone-naive event times as UTC.
    if event_start.tzinfo is None:
        event_start = event_start.replace(
            tzinfo=timezone.utc
        )

    if event_start <= now:
        raise PaymentValidationError(
            "Payment is no longer available because the event has started."
        )

    # ---------------------------------------
    # 5. Lock the booking
    # ---------------------------------------

    booking = db.scalar(
        select(Booking)
        .where(Booking.id == booking_id)
        .with_for_update()
    )

    if booking is None:
        raise PaymentValidationError(
            "Booking not found."
        )

    # ---------------------------------------
    # 6. Validate booking ownership
    # ---------------------------------------

    if booking.user_id != user_id:
        raise PaymentValidationError(
            "You cannot pay for another attendee's booking."
        )

    # ---------------------------------------
    # 7. Validate booking status
    # ---------------------------------------

    if booking.status == BookingStatus.CANCELLED:
        raise PaymentValidationError(
            "Cancelled bookings cannot be paid."
        )

    if booking.status == BookingStatus.CONFIRMED:
        raise PaymentValidationError(
            "This booking has already been confirmed."
        )

    if booking.status != BookingStatus.PENDING:
        raise PaymentValidationError(
            "This booking cannot be paid."
        )

    # ---------------------------------------
    # 8. Validate quantity and amount
    # ---------------------------------------

    if booking.quantity <= 0:
        raise PaymentValidationError(
            "Invalid booking quantity."
        )

    if booking.total_amount < 0:
        raise PaymentValidationError(
            "Invalid payment amount."
        )

    # ---------------------------------------
    # 9. Prevent duplicate payments
    # ---------------------------------------

    existing_payment = db.scalar(
        select(Payment).where(
            Payment.booking_id == booking.id
        )
    )

    if existing_payment is not None:
        raise PaymentValidationError(
            "A payment already exists for this booking."
        )

    # ---------------------------------------
    # 10. Prevent duplicate tickets
    # ---------------------------------------

    existing_ticket = db.scalar(
        select(Ticket).where(
            Ticket.booking_id == booking.id
        )
    )

    if existing_ticket is not None:
        raise PaymentValidationError(
            "Tickets already exist for this booking."
        )

    # ---------------------------------------
    # 11. Create simulated payment
    # ---------------------------------------

    payment_reference = (
        "PAY-" + uuid.uuid4().hex.upper()
    )

    payment = Payment(
        booking_id=booking.id,
        payment_reference=payment_reference,
        amount=booking.total_amount,
        refunded_amount=0,
        status=PaymentStatus.SUCCESS,
    )

    db.add(payment)

    # ---------------------------------------
    # 12. Confirm booking
    # ---------------------------------------

    booking.status = BookingStatus.CONFIRMED

    # ---------------------------------------
    # 13. Generate individual tickets
    # ---------------------------------------

    tickets = []

    for _ in range(booking.quantity):
        ticket = Ticket(
            booking_id=booking.id,
            event_id=booking.event_id,
            ticket_category_id=booking.ticket_category_id,
            qr_token=secrets.token_urlsafe(32),
            status=TicketStatus.VALID,
            scan_attempts=0,
        )

        db.add(ticket)
        tickets.append(ticket)

    # ---------------------------------------
    # 14. Flush the transaction
    # ---------------------------------------

    # The payment, booking update and tickets
    # are written within the same transaction.
    db.flush()

    # Do not commit here.
    # The caller must commit or roll back.

    return payment, booking, tickets
