
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.models import (
    AgentInbox,
    AgentMessage,
    AgentState,
    MessagePerformative,
)


AGENT_NAMES = {
    "VenueAgent",
    "BookingAgent",
    "TicketAgent",
    "WaitlistAgent",
    "NotificationAgent",
}


def send_message(
    db: Session,
    sender: str,
    receiver: str,
    performative: MessagePerformative,
    content: dict,
    conversation_id: str | None = None,
):
    """
    Send a structured JSON message between agents.

    The message is recorded in the agent message log
    and delivered to the receiving agent's inbox.
    """

    if sender not in AGENT_NAMES and sender != "System":
        raise ValueError(f"Unknown sender: {sender}")

    if receiver not in AGENT_NAMES:
        raise ValueError(f"Unknown receiver: {receiver}")

    if not isinstance(content, dict):
        raise ValueError("Message content must be a dictionary.")

    if not isinstance(performative, MessagePerformative):
        performative = MessagePerformative(performative)

    if performative in (
        MessagePerformative.REFUSE,
        MessagePerformative.PROPOSE,
    ):
        if not content.get("reason"):
            raise ValueError(
                "REFUSE and PROPOSE messages require a reason."
            )

    if performative == MessagePerformative.PROPOSE:
        if not content.get("alternatives"):
            raise ValueError(
                "PROPOSE messages require alternatives."
            )

    message_id = str(uuid.uuid4())
    conversation_id = conversation_id or str(uuid.uuid4())

    payload = {
        "message_id": message_id,
        "conversation_id": conversation_id,
        "sender": sender,
        "receiver": receiver,
        "performative": performative.value,
        "content": content,
    }

    message = AgentMessage(
        message_id=message_id,
        conversation_id=conversation_id,
        sender=sender,
        receiver=receiver,
        performative=performative,
        content=content,
    )

    inbox = AgentInbox(
        message_id=message_id,
        receiver=receiver,
        payload=payload,
        processed=False,
    )

    db.add(message)
    db.add(inbox)
    db.flush()

    return payload


def get_pending_messages(
    db: Session,
    receiver: str,
):
    """
    Retrieve unprocessed messages for an agent.
    """

    return db.scalars(
        select(AgentInbox)
        .where(
            AgentInbox.receiver == receiver,
            AgentInbox.processed.is_(False),
        )
        .order_by(AgentInbox.created_at, AgentInbox.id)
    ).all()


def mark_message_processed(
    db: Session,
    inbox_message: AgentInbox,
):
    """
    Mark an inbox message as processed.
    """

    inbox_message.processed = True
    inbox_message.processed_at = datetime.now(timezone.utc)

    db.flush()


def get_agent_state(
    db: Session,
    agent_name: str,
):
    """
    Read persistent state for an agent.
    """

    state = db.scalar(
        select(AgentState).where(
            AgentState.agent_name == agent_name
        )
    )

    if state is None:
        return {}

    return dict(state.state_data)


def update_agent_state(
    db: Session,
    agent_name: str,
    state_data: dict,
):
    """
    Create or update an agent's persistent state.
    """

    if agent_name not in AGENT_NAMES:
        raise ValueError("Unknown agent name.")

    state = db.scalar(
        select(AgentState).where(
            AgentState.agent_name == agent_name
        )
    )

    if state is None:
        state = AgentState(
            agent_name=agent_name,
            state_data=dict(state_data),
        )
        db.add(state)
    else:
        state.state_data = dict(state_data)
        state.updated_at = datetime.now(timezone.utc)

    db.flush()

    return state
