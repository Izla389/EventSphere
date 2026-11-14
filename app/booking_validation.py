
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.models import (
    Booking,
    BookingStatus,
    Event,
    EventStatus,
    TicketCategory,
)


MAX_TICKETS_PER_BOOKING = 10
MONEY_PLACES = Decimal("0.01")


class BookingValidationError(ValueError):
    """Raised when a booking does not satisfy business rules."""


def validate_booking_quantity(value) -> int:
    """
    Accept a whole-number quantity from an HTML form.
    Valid range: 1 to 10.
    """

    if isinstance(value, bool):
        raise BookingValidationError(
            "Ticket quantity must be a whole number."
        )

    if isinstance(value, int):
        quantity = value
    elif isinstance(value, str):
        cleaned = value.strip()

        if not cleaned.isascii() or not cleaned.isdecimal():
            raise BookingValidationError(
                "Ticket quantity must be a whole number."
            )

        quantity = int(cleaned)
    else:
        raise BookingValidationError(
            "Ticket quantity must be a whole number."
        )

    if quantity < 1 or quantity > MAX_TICKETS_PER_BOOKING:
        raise BookingValidationError(
            "You can book between 1 and 10 tickets at a time."
        )

    return quantity


def validate_event_bookable(
    event: Event,
    now: datetime | None = None,
) -> None:
    """
    Check that an event exists, is published,
    and has not started.
    """

    if event is None:
        raise BookingValidationError(
            "Event not found."
        )

    if event.status != EventStatus.PUBLISHED:
        raise BookingValidationError(
            "This event is not available for booking."
        )

    if now is None:
        now = datetime.now(timezone.utc)

    start_time = event.start_time

    # SQLite may return naive datetimes in tests.
    # Our application stores event times as UTC.
    if start_time.tzinfo is None:
        start_time = start_time.replace(
            tzinfo=timezone.utc
        )

    if start_time <= now:
        raise BookingValidationError(
            "Bookings are closed because this event has started."
        )


def calculate_booking_total(
    price,
    quantity,
) -> Decimal:
    """
    Calculate the booking total using Decimal.
    """

    valid_quantity = validate_booking_quantity(quantity)

    if isinstance(price, bool) or isinstance(price, float):
        raise BookingValidationError(
            "Ticket price must be a valid decimal amount."
        )

    try:
        amount = Decimal(str(price))
    except (InvalidOperation, ValueError, TypeError):
        raise BookingValidationError(
            "Ticket price must be a valid decimal amount."
        )

    if not amount.is_finite() or amount < 0:
        raise BookingValidationError(
            "Ticket price cannot be negative."
        )

    if amount != amount.quantize(MONEY_PLACES):
        raise BookingValidationError(
            "Ticket price cannot have more than two decimal places."
        )

    total = amount * valid_quantity

    return total.quantize(
        MONEY_PLACES,
        rounding=ROUND_HALF_UP,
    )


def get_available_tickets(
    category: TicketCategory,
) -> int:
    """
    Return the remaining ticket inventory.
    """

    if category is None:
        raise BookingValidationError(
            "Ticket category not found."
        )

    available = category.quantity - category.sold_count

    if available < 0:
        raise BookingValidationError(
            "Ticket inventory is inconsistent."
        )

    return available


def check_ticket_availability(
    category: TicketCategory,
    quantity,
) -> int:
    """
    Validate the requested quantity against inventory.
    Returns the validated quantity.
    """

    valid_quantity = validate_booking_quantity(quantity)

    available = get_available_tickets(category)

    if valid_quantity > available:
        raise BookingValidationError(
            f"Only {available} ticket(s) are available."
        )

    return valid_quantity


def reserve_booking(
    db: Session,
    *,
    user_id: int,
    event_id: int,
    ticket_category_id: int,
    quantity,
) -> Booking:
    """
    Reserve tickets and create a PENDING booking.

    PostgreSQL locks the ticket category row to prevent
    concurrent reservations from overselling tickets.

    IMPORTANT:
    The caller must commit the transaction.
    This function does not commit.
    """

    valid_quantity = validate_booking_quantity(quantity)

    # First identify the event.
    #event = db.get(Event, event_id)

    #validate_event_bookable(event)

    # Lock the event before checking its current status.
    # This is the first lock in our booking transaction.
    event = db.execute(
        select(Event)
        .where(Event.id == event_id)
        .with_for_update()
    ).scalar_one_or_none()
    

    validate_event_bookable(event)

    # Lock the ticket category row until the transaction ends.
    category = db.execute(
        select(TicketCategory)
        .where(
            TicketCategory.id == ticket_category_id
        )
        .with_for_update()
    ).scalar_one_or_none()


    # Lock the ticket category row until the transaction ends.
    category = db.execute(
        select(TicketCategory)
        .where(
            TicketCategory.id == ticket_category_id
        )
        .with_for_update()
    ).scalar_one_or_none()

    if category is None:
        raise BookingValidationError(
            "Ticket category not found."
        )

    if category.event_id != event_id:
        raise BookingValidationError(
            "This ticket category does not belong to the event."
        )

    # Recheck availability while holding the row lock.
    check_ticket_availability(
        category,
        valid_quantity,
    )

    total = calculate_booking_total(
        category.price,
        valid_quantity,
    )

    category.sold_count += valid_quantity

    booking = Booking(
        user_id=user_id,
        event_id=event_id,
        ticket_category_id=category.id,
        quantity=valid_quantity,
        total_amount=total,
        refund_amount=Decimal("0.00"),
        status=BookingStatus.PENDING,
    )

    db.add(booking)
    db.flush()

    return booking
