
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.message_bus import (
    get_agent_state,
    get_pending_messages,
    mark_message_processed,
    send_message,
    update_agent_state,
)
from app.models.models import (
    Booking,
    BookingStatus,
    Event,
    EventStatus,
    MessagePerformative,
    TicketCategory,
)


AGENT_NAME = "BookingAgent"
MAX_TICKETS_PER_BOOKING = 6


def evaluate_booking(
    db: Session,
    event_id: int,
    ticket_category_id: int,
    quantity: int,
):
    """
    Evaluate whether a ticket request is allowed.

    This function only evaluates availability.
    It does not reserve tickets or take payment.
    """

    event = db.get(Event, event_id)

    if event is None:
        return {
            "approved": False,
            "reason": "Event does not exist.",
        }

    if event.status != EventStatus.PUBLISHED:
        return {
            "approved": False,
            "reason": "Event is not published.",
        }

    if quantity < 1 or quantity > MAX_TICKETS_PER_BOOKING:
        return {
            "approved": False,
            "reason": (
                "Booking quantity must be between "
                f"1 and {MAX_TICKETS_PER_BOOKING}."
            ),
        }

    category = db.get(
        TicketCategory,
        ticket_category_id,
    )

    if category is None or category.event_id != event_id:
        return {
            "approved": False,
            "reason": "Invalid ticket category.",
        }

    remaining = category.quantity - category.sold_count

    if quantity > remaining:
        return {
            "approved": False,
            "reason": "Not enough tickets are available.",
        }

    return {
        "approved": True,
        "reason": "Tickets are available.",
        "total_amount": str(
            Decimal(str(category.price)) * quantity
        ),
    }


def calculate_refund(
    booking: Booking,
    event_cancelled: bool = False,
):
    """
    Calculate the refund amount.

    Full refund:
        Event cancelled by organiser.

    Otherwise:
        This initial rule gives a 50% refund
        for an attendee cancellation.
    """

    amount = Decimal(str(booking.total_amount))

    if event_cancelled:
        return amount

    return (amount * Decimal("0.50")).quantize(
        Decimal("0.01")
    )


def process_booking_requests(db: Session):
    """
    Process REQUEST messages sent to BookingAgent.

    Supported action:
        evaluate_booking
    """

    pending = get_pending_messages(db, AGENT_NAME)
    state = get_agent_state(db, AGENT_NAME)

    decisions = state.get("decisions", 0)
    processed = 0

    for inbox_message in pending:
        payload = inbox_message.payload
        content = payload.get("content", {})

        if payload.get("performative") != "REQUEST":
            continue

        if content.get("action") != "evaluate_booking":
            continue

        result = evaluate_booking(
            db,
            event_id=content.get("event_id"),
            ticket_category_id=content.get(
                "ticket_category_id"
            ),
            quantity=content.get("quantity", 0),
        )

        if result["approved"]:
            send_message(
                db,
                sender=AGENT_NAME,
                receiver="TicketAgent",
                performative=MessagePerformative.AGREE,
                content={
                    "event_id": content.get("event_id"),
                    "ticket_category_id": content.get(
                        "ticket_category_id"
                    ),
                    "quantity": content.get("quantity"),
                    "total_amount": result["total_amount"],
                    "reason": result["reason"],
                },
                conversation_id=payload["conversation_id"],
            )

        else:
            send_message(
                db,
                sender=AGENT_NAME,
                receiver="NotificationAgent",
                performative=MessagePerformative.INFORM,
                content={
                    "user_id": content.get("user_id"),
                    "title": "Booking Request Rejected",
                    "message": result["reason"],
                },
                conversation_id=payload["conversation_id"],
            )

        mark_message_processed(db, inbox_message)

        processed += 1
        decisions += 1

    update_agent_state(
        db,
        AGENT_NAME,
        {"decisions": decisions},
    )

    db.commit()

    return {
        "agent": AGENT_NAME,
        "processed": processed,
        "decisions": decisions,
    }
