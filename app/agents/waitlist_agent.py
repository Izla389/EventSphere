
import secrets
from datetime import datetime, timedelta, timezone

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
    MessagePerformative,
    TicketCategory,
    WaitlistEntry,
    WaitlistStatus,
)


AGENT_NAME = "WaitlistAgent"
OFFER_DURATION_MINUTES = 15


def now_utc():
    return datetime.now(timezone.utc)


def make_aware(value):
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def notify_user(
    db: Session,
    user_id: int,
    title: str,
    message: str,
    conversation_id: str | None = None,
):
    send_message(
        db,
        sender=AGENT_NAME,
        receiver="NotificationAgent",
        performative=MessagePerformative.INFORM,
        content={
            "user_id": user_id,
            "title": title,
            "message": message,
        },
        conversation_id=conversation_id,
    )


def expire_offers(db: Session):
    """
    Expire offers that have passed their deadline.
    """

    current_time = now_utc()

    offered_entries = db.scalars(
        select(WaitlistEntry).where(
            WaitlistEntry.status == WaitlistStatus.OFFERED
        )
    ).all()

    expired_count = 0

    for entry in offered_entries:
        expiry = make_aware(entry.offer_expires_at)

        if expiry is None or expiry > current_time:
            continue

        entry.status = WaitlistStatus.EXPIRED
        entry.hold_token = None

        notify_user(
            db,
            user_id=entry.user_id,
            title="Ticket Offer Expired",
            message=(
                "Your waitlist ticket offer has expired. "
                "The tickets may be offered to another customer."
            ),
        )

        expired_count += 1

    return expired_count


def offer_available_tickets(
    db: Session,
    ticket_category_id: int,
    conversation_id: str | None = None,
):
    """
    Offer currently available tickets to waiting users.

    Outstanding offers are treated as reserved capacity
    to avoid offering the same seats multiple times.

    IMPORTANT:
    The final booking operation must also enforce these
    reservations under a database transaction.
    """

    category = db.get(
        TicketCategory,
        ticket_category_id,
    )

    if category is None:
        return 0

    active_offers = db.scalars(
        select(WaitlistEntry).where(
            WaitlistEntry.ticket_category_id
            == ticket_category_id,
            WaitlistEntry.status == WaitlistStatus.OFFERED,
        )
    ).all()

    held_quantity = sum(
        entry.quantity for entry in active_offers
    )

    available = (
        category.quantity
        - category.sold_count
        - held_quantity
    )

    if available <= 0:
        return 0

    waiting_entries = db.scalars(
        select(WaitlistEntry)
        .where(
            WaitlistEntry.ticket_category_id
            == ticket_category_id,
            WaitlistEntry.status == WaitlistStatus.WAITING,
        )
        .order_by(
            WaitlistEntry.created_at,
            WaitlistEntry.id,
        )
    ).all()

    offered_count = 0

    for entry in waiting_entries:
        if entry.quantity > available:
            continue

        entry.status = WaitlistStatus.OFFERED
        entry.offered_at = now_utc()
        entry.offer_expires_at = (
            now_utc()
            + timedelta(minutes=OFFER_DURATION_MINUTES)
        )
        entry.hold_token = secrets.token_urlsafe(32)

        notify_user(
            db,
            user_id=entry.user_id,
            title="Waitlist Ticket Offer",
            message=(
                f"{entry.quantity} ticket(s) are available. "
                f"Your offer expires in "
                f"{OFFER_DURATION_MINUTES} minutes."
            ),
            conversation_id=conversation_id,
        )

        available -= entry.quantity
        offered_count += 1

        if available <= 0:
            break

    return offered_count


def process_waitlist_requests(db: Session):
    """
    Process REQUEST messages sent to WaitlistAgent.

    Supported action:
        check_availability
    """

    pending = get_pending_messages(db, AGENT_NAME)
    state = get_agent_state(db, AGENT_NAME)

    processed = 0
    total_offers = state.get("total_offers", 0)

    for inbox_message in pending:
        payload = inbox_message.payload
        content = payload.get("content", {})

        if payload.get("performative") != "REQUEST":
            continue

        if content.get("action") != "check_availability":
            continue

        category_id = content.get("ticket_category_id")

        offers = offer_available_tickets(
            db,
            ticket_category_id=category_id,
            conversation_id=payload["conversation_id"],
        )

        total_offers += offers
        processed += 1

        mark_message_processed(
            db,
            inbox_message,
        )

    update_agent_state(
        db,
        AGENT_NAME,
        {"total_offers": total_offers},
    )

    db.commit()

    return {
        "agent": AGENT_NAME,
        "processed": processed,
        "total_offers": total_offers,
    }


def run_waitlist_timer(db: Session):
    """
    Execute one timer cycle.

    Intended to be called by an external scheduler
    without requiring a user request.
    """

    expired_count = expire_offers(db)

    category_ids = db.scalars(
        select(WaitlistEntry.ticket_category_id)
        .where(
            WaitlistEntry.status == WaitlistStatus.WAITING
        )
        .distinct()
    ).all()

    offered_count = 0

    for category_id in category_ids:
        offered_count += offer_available_tickets(
            db,
            ticket_category_id=category_id,
        )

    state = get_agent_state(db, AGENT_NAME)

    update_agent_state(
        db,
        AGENT_NAME,
        {
            **state,
            "timer_runs": state.get("timer_runs", 0) + 1,
            "total_offers": (
                state.get("total_offers", 0)
                + offered_count
            ),
            "total_expired": (
                state.get("total_expired", 0)
                + expired_count
            ),
        },
    )

    db.commit()

    return {
        "expired": expired_count,
        "offered": offered_count,
    }
