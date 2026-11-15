
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.models import (
    Booking,
    BookingStatus,
    Event,
    EventStatus,
    Ticket,
    TicketStatus,
    User,
    UserRole,
)


class CheckInValidationError(Exception):
    """
    Raised when a ticket cannot be checked in.

    save_scan_attempt indicates whether the caller may
    commit the rejected scan attempt.
    """

    def __init__(
        self,
        message: str,
        *,
        save_scan_attempt: bool = False,
    ):
        super().__init__(message)
        self.save_scan_attempt = save_scan_attempt


def check_in_ticket(
    db: Session,
    *,
    qr_token: str,
    event_id: int,
    staff_user_id: int,
) -> Ticket:
    """
    Validate and check in a ticket.

    The caller must commit after success.

    For rejected scans of an existing ticket, the caller
    may commit the scan-attempt increment when the
    exception's save_scan_attempt flag is True.

    PostgreSQL row locking prevents simultaneous
    check-ins of the same ticket.
    """

    if not qr_token or not qr_token.strip():
        raise CheckInValidationError(
            "QR token is required."
        )

    if event_id <= 0:
        raise CheckInValidationError(
            "Invalid event ID."
        )

    staff = db.get(User, staff_user_id)

    if staff is None or not staff.is_active:
        raise CheckInValidationError(
            "Staff account is not active."
        )

    if staff.role not in (
        UserRole.STAFF,
        UserRole.ADMIN,
    ):
        raise CheckInValidationError(
            "You are not authorized to check in tickets."
        )

    event = db.get(Event, event_id)

    if event is None:
        raise CheckInValidationError(
            "Event not found."
        )

    if event.status != EventStatus.PUBLISHED:
        raise CheckInValidationError(
            "This event is not active."
        )

    ticket = db.scalar(
        select(Ticket)
        .where(Ticket.qr_token == qr_token.strip())
        .with_for_update()
    )

    if ticket is None:
        raise CheckInValidationError(
            "Invalid QR ticket."
        )

    # Count each scan of an existing ticket.
    ticket.scan_attempts += 1

    if ticket.event_id != event_id:
        raise CheckInValidationError(
            "This ticket belongs to another event.",
            save_scan_attempt=True,
        )

    booking = db.get(Booking, ticket.booking_id)

    if booking is None:
        raise CheckInValidationError(
            "Booking not found.",
            save_scan_attempt=True,
        )

    if booking.status != BookingStatus.CONFIRMED:
        raise CheckInValidationError(
            "This booking is not confirmed.",
            save_scan_attempt=True,
        )

    if booking.event_id != event_id:
        raise CheckInValidationError(
            "Booking does not belong to this event.",
            save_scan_attempt=True,
        )

    if ticket.status == TicketStatus.USED:
        raise CheckInValidationError(
            "This ticket has already been checked in.",
            save_scan_attempt=True,
        )

    if ticket.status == TicketStatus.CANCELLED:
        raise CheckInValidationError(
            "This ticket has been cancelled.",
            save_scan_attempt=True,
        )

    if ticket.status != TicketStatus.VALID:
        raise CheckInValidationError(
            "Ticket is not valid.",
            save_scan_attempt=True,
        )

    ticket.status = TicketStatus.USED
    ticket.checked_in_at = datetime.now(timezone.utc)
    ticket.checked_in_by = staff_user_id

    db.flush()

    return ticket
