
from sqlalchemy.orm import Session

from app.agents.message_bus import (
    get_agent_state,
    get_pending_messages,
    mark_message_processed,
    update_agent_state,
)
from app.models.models import (
    MessagePerformative,
    Notification,
    User,
)


AGENT_NAME = "NotificationAgent"


def process_notifications(db: Session):
    """
    Process pending messages sent to NotificationAgent.

    This agent reacts to INFORM messages from other
    agents and creates user notifications.
    """

    pending_messages = get_pending_messages(
        db,
        AGENT_NAME,
    )

    state = get_agent_state(db, AGENT_NAME)

    total_notifications = state.get(
        "total_notifications",
        0,
    )

    processed_count = 0

    for inbox_message in pending_messages:
        payload = inbox_message.payload

        performative = payload.get("performative")
        content = payload.get("content", {})

        if performative != MessagePerformative.INFORM.value:
            # Do not silently discard unsupported messages.
            # Leave them pending for investigation.
            continue

        user_id = content.get("user_id")
        title = content.get("title")
        message_text = content.get("message")

        if not user_id or not title or not message_text:
            # Leave invalid messages pending.
            continue

        user = db.get(User, user_id)

        if user is None:
            # Leave messages with unknown users pending.
            continue

        notification = Notification(
            user_id=user.id,
            title=title,
            message=message_text,
            conversation_id=payload.get("conversation_id"),
        )

        db.add(notification)

        mark_message_processed(
            db,
            inbox_message,
        )

        total_notifications += 1
        processed_count += 1

    update_agent_state(
        db,
        AGENT_NAME,
        {
            "total_notifications": total_notifications,
        },
    )

    db.commit()

    return {
        "agent": AGENT_NAME,
        "processed": processed_count,
        "total_notifications": total_notifications,
    }
