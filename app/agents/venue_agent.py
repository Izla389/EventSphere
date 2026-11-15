
from datetime import timedelta
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
    Event,
    EventStatus,
    HireStatus,
    MessagePerformative,
    Venue,
    VenueHireRequest,
)


AGENT_NAME = "VenueAgent"
TURNAROUND_MINUTES = 30


def has_schedule_conflict(
    db: Session,
    venue_id: int,
    start_time,
    end_time,
):
    """
    Check whether the venue has conflicting events
    or confirmed private hire bookings.

    A 30-minute turnaround buffer is enforced.
    """

    buffer = timedelta(minutes=TURNAROUND_MINUTES)

    events = db.scalars(
        select(Event).where(
            Event.venue_id == venue_id,
            Event.status != EventStatus.CANCELLED,
        )
    ).all()

    for event in events:
        if (
            start_time < event.end_time + buffer
            and end_time > event.start_time - buffer
        ):
            return True

    hires = db.scalars(
        select(VenueHireRequest).where(
            VenueHireRequest.venue_id == venue_id,
            VenueHireRequest.status == HireStatus.CONFIRMED,
        )
    ).all()

    for hire in hires:
        if (
            start_time < hire.end_time + buffer
            and end_time > hire.start_time - buffer
        ):
            return True

    return False


def suggest_alternative_times(
    db: Session,
    venue_id: int,
    start_time,
    end_time,
):
    """
    Suggest available alternative time slots.
    """

    duration = end_time - start_time
    alternatives = []

    for days_ahead in range(1, 8):
        new_start = start_time + timedelta(days=days_ahead)
        new_end = new_start + duration

        if not has_schedule_conflict(
            db,
            venue_id,
            new_start,
            new_end,
        ):
            alternatives.append({
                "venue_id": venue_id,
                "start_time": new_start.isoformat(),
                "end_time": new_end.isoformat(),
            })

        if len(alternatives) >= 3:
            break

    return alternatives


def calculate_hire_price(
    venue: Venue,
    start_time,
    end_time,
):
    """
    Calculate private hire price from hourly rate.
    """

    duration_hours = Decimal(
        str((end_time - start_time).total_seconds())
    ) / Decimal("3600")

    return (
        Decimal(str(venue.hourly_hire_rate))
        * duration_hours
    ).quantize(Decimal("0.01"))


def process_venue_requests(db: Session):
    """
    Handle REQUEST messages sent to VenueAgent.

    Supported action:
        evaluate_hire

    VenueAgent decides whether to:
    - Confirm a hire.
    - Propose alternative times.
    - Refuse an invalid request.
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

        if content.get("action") != "evaluate_hire":
            continue

        hire_id = content.get("hire_id")
        hire = db.get(VenueHireRequest, hire_id)

        if hire is None:
            send_message(
                db,
                sender=AGENT_NAME,
                receiver=payload["sender"],
                performative=MessagePerformative.REFUSE,
                content={
                    "reason": "Venue hire request not found.",
                },
                conversation_id=payload["conversation_id"],
            )

            mark_message_processed(db, inbox_message)
            processed += 1
            decisions += 1
            continue

        venue = db.get(Venue, hire.venue_id)

        if venue is None or not venue.is_open_for_hire:
            hire.status = HireStatus.REJECTED
            hire.decision_reason = (
                "Venue is not available for private hire."
            )

            send_message(
                db,
                sender=AGENT_NAME,
                receiver="NotificationAgent",
                performative=MessagePerformative.INFORM,
                content={
                    "user_id": hire.user_id,
                    "title": "Venue Hire Rejected",
                    "message": hire.decision_reason,
                },
                conversation_id=payload["conversation_id"],
            )

        elif hire.guest_count > venue.capacity:
            hire.status = HireStatus.ESCALATED
            hire.decision_reason = (
                "Guest count exceeds venue capacity."
            )

            send_message(
                db,
                sender=AGENT_NAME,
                receiver="NotificationAgent",
                performative=MessagePerformative.INFORM,
                content={
                    "user_id": hire.user_id,
                    "title": "Venue Hire Needs Review",
                    "message": hire.decision_reason,
                },
                conversation_id=payload["conversation_id"],
            )

        elif has_schedule_conflict(
            db,
            hire.venue_id,
            hire.start_time,
            hire.end_time,
        ):
            alternatives = suggest_alternative_times(
                db,
                hire.venue_id,
                hire.start_time,
                hire.end_time,
            )

            hire.status = HireStatus.ESCALATED
            hire.decision_reason = (
                "Requested time conflicts with another booking."
            )
            hire.alternatives = alternatives

            if alternatives:
                send_message(
                    db,
                    sender=AGENT_NAME,
                    receiver="NotificationAgent",
                    performative=MessagePerformative.INFORM,
                    content={
                        "user_id": hire.user_id,
                        "title": "Alternative Venue Times",
                        "message": (
                            "Your requested slot is unavailable. "
                            "Alternative times have been suggested."
                        ),
                    },
                    conversation_id=payload["conversation_id"],
                )

        else:
            hire.status = HireStatus.CONFIRMED
            hire.quoted_price = calculate_hire_price(
                venue,
                hire.start_time,
                hire.end_time,
            )
            hire.decision_reason = (
                "Automatically confirmed by VenueAgent."
            )

            send_message(
                db,
                sender=AGENT_NAME,
                receiver="NotificationAgent",
                performative=MessagePerformative.INFORM,
                content={
                    "user_id": hire.user_id,
                    "title": "Venue Hire Confirmed",
                    "message": (
                        f"Your venue hire is confirmed. "
                        f"Price: {hire.quoted_price}"
                    ),
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
