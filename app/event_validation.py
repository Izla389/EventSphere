
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

from sqlalchemy import select, and_, or_
from sqlalchemy.orm import Session

from app.models.models import (
    Event,
    EventStatus,
    TicketCategory,
    Venue,
    VenueHireRequest,
    HireStatus,
)


class EventValidationError(ValueError):
    """Raised when event information is invalid."""
    pass


def parse_datetime(value: str) -> datetime:
    """Convert an HTML datetime-local value to a UTC datetime."""
    try:
        result = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        raise EventValidationError("Enter a valid date and time.")

    if result.tzinfo is None:
        raise EventValidationError(
            "Date and time must include a timezone offset."
        )

    return result.astimezone(timezone.utc)


def validate_event(
    title: str,
    category: str,
    start_time: str,
    end_time: str,
    description: str,
    image_url: str,
) -> dict:
    title = title.strip()
    category = category.strip()
    description = description.strip()
    image_url = image_url.strip()

    if not 2 <= len(title) <= 200:
        raise EventValidationError(
            "Event title must contain 2 to 200 characters."
        )

    if not 2 <= len(category) <= 100:
        raise EventValidationError(
            "Event category must contain 2 to 100 characters."
        )

    if len(description) > 5000:
        raise EventValidationError(
            "Description cannot exceed 5000 characters."
        )

    if image_url:
        parsed = urlparse(image_url)
        if (
            len(image_url) > 500
            or parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
        ):
            raise EventValidationError(
                "Image URL must be a valid HTTPS URL."
            )

    start = parse_datetime(start_time)
    end = parse_datetime(end_time)

    if end <= start:
        raise EventValidationError(
            "Event end time must be after its start time."
        )

    if start <= datetime.now(timezone.utc):
        raise EventValidationError(
            "Event start time must be in the future."
        )

    return {
        "title": title,
        "category": category,
        "start_time": start,
        "end_time": end,
        "description": description or None,
        "image_url": image_url or None,
    }


def check_venue_availability(
    db: Session,
    venue_id: int,
    start_time: datetime,
    end_time: datetime,
    exclude_event_id: int | None = None,
) -> None:
    """Reject scheduling conflicts for the selected venue."""

    query = select(Event).where(
        Event.venue_id == venue_id,
        Event.status != EventStatus.CANCELLED,
        Event.start_time < end_time,
        Event.end_time > start_time,
    )

    if exclude_event_id is not None:
        query = query.where(Event.id != exclude_event_id)

    conflicting_event = db.scalar(query)

    if conflicting_event is not None:
        raise EventValidationError(
            "This venue already has an event during the selected time."
        )

    conflicting_hire = db.scalar(
        select(VenueHireRequest).where(
            VenueHireRequest.venue_id == venue_id,
            VenueHireRequest.status == HireStatus.CONFIRMED,
            VenueHireRequest.start_time < end_time,
            VenueHireRequest.end_time > start_time,
        )
    )

    if conflicting_hire is not None:
        raise EventValidationError(
            "This venue has a confirmed private hire during that time."
        )


def validate_ticket_category(
    name: str,
    price: str,
    quantity: str,
) -> dict:
    name = name.strip()

    if not 2 <= len(name) <= 100:
        raise EventValidationError(
            "Ticket category name must contain 2 to 100 characters."
        )

    try:
        parsed_price = Decimal(price)
    except (InvalidOperation, TypeError):
        raise EventValidationError(
            "Ticket price must be a valid number."
        )

    if (
        not parsed_price.is_finite()
        or parsed_price < 0
        or parsed_price > Decimal("9999999999.99")
        or parsed_price.as_tuple().exponent < -2
    ):
        raise EventValidationError(
            "Ticket price must be non-negative with at most two decimal places."
        )

    try:
        parsed_quantity = int(quantity)
    except (ValueError, TypeError):
        raise EventValidationError(
            "Ticket quantity must be a whole number."
        )

    if parsed_quantity < 1 or parsed_quantity > 1_000_000:
        raise EventValidationError(
            "Ticket quantity must be between 1 and 1,000,000."
        )

    return {
        "name": name,
        "price": parsed_price,
        "quantity": parsed_quantity,
    }


def check_ticket_capacity(
    db: Session,
    event_id: int,
    venue_capacity: int,
    new_quantity: int,
    exclude_category_id: int | None = None,
) -> None:
    """Ensure total ticket allocations do not exceed venue capacity."""

    query = select(TicketCategory).where(
        TicketCategory.event_id == event_id
    )

    if exclude_category_id is not None:
        query = query.where(
            TicketCategory.id != exclude_category_id
        )

    existing_categories = db.scalars(query).all()

    total = sum(
        category.quantity for category in existing_categories
    )

    if total + new_quantity > venue_capacity:
        raise EventValidationError(
            f"Total ticket quantity cannot exceed venue capacity "
            f"({venue_capacity})."
        )
