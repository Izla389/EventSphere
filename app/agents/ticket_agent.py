
import secrets

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
    MessagePerformative,
    Ticket,
    TicketStatus,
)


AGENT_NAME = "TicketAgent"


def generate_ticket_token():
    """
    Generate a cryptographically secure,
    unguessable ticket token.
    """
    return secrets.token_urlsafe(32)


def evaluate_ticket(
    db: Session,
    qr_token: str,
    event_id: int,
):
    """
    Evaluate a ticket without changing its status.

    The existing check-in service remains responsible
    for securely admitting tickets.
    """

    ticket = db.scalar(
        select(Ticket).where(
            Ticket.qr_token == qr_token
        )
    )

    if ticket is None:
        return {
            "admitted": False,
            "reason": "Ticket not found.",
        }

    if ticket.event_id != event_id:
        return {
            "admitted": False,
            "reason": "Ticket belongs to another event.",
        }

    booking = db.get(Booking, ticket.booking_id)

    if (
        booking is None
        or booking.status != BookingStatus.CONFIRMED
    ):
        return {
            "admitted": False,
            "reason": "Booking is not confirmed.",
        }

    if ticket.status == TicketStatus.CANCELLED:
        return {
            "admitted": False,
            "reason": "Ticket has been cancelled.",
        }

    if ticket.status == TicketStatus.USED:
        return {
            "admitted": False,
            "reason": "Ticket has already been used.",
        }

    return {
        "admitted": True,
        "reason": "Ticket is valid for check-in.",
        "ticket_id": ticket.id,
    }


def process_ticket_requests(db: Session):
    """
    Process messages received by TicketAgent.

    This handler records ticket validation decisions.
    It does not directly admit attendees.
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

        if content.get("action") != "validate_ticket":
            continue

        result = evaluate_ticket(
            db,
            qr_token=content.get("qr_token", ""),
            event_id=content.get("event_id"),
        )

        send_message(
            db,
            sender=AGENT_NAME,
            receiver="BookingAgent",
            performative=(
                MessagePerformative.AGREE
                if result["admitted"]
                else MessagePerformative.REFUSE
            ),
            content=result,
            conversation_id=payload["conversation_id"],
        )

        mark_message_processed(
            db,
            inbox_message,
        )

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
