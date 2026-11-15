import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Index,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def utc_now():
    return datetime.now(timezone.utc)


def new_uuid():
    return str(uuid.uuid4())


# -----------------------------
# ENUMS
# -----------------------------

class UserRole(str, enum.Enum):
    ADMIN = "admin"
    STAFF = "staff"
    ATTENDEE = "attendee"


class EventStatus(str, enum.Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    CANCELLED = "cancelled"


class BookingStatus(str, enum.Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


class TicketStatus(str, enum.Enum):
    VALID = "valid"
    USED = "used"
    CANCELLED = "cancelled"


class PaymentStatus(str, enum.Enum):
    SUCCESS = "success"
    REFUNDED = "refunded"
    PARTIALLY_REFUNDED = "partially_refunded"


class HireStatus(str, enum.Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    ESCALATED = "escalated"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class WaitlistStatus(str, enum.Enum):
    WAITING = "waiting"
    OFFERED = "offered"
    CLAIMED = "claimed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class MessagePerformative(str, enum.Enum):
    REQUEST = "REQUEST"
    AGREE = "AGREE"
    REFUSE = "REFUSE"
    PROPOSE = "PROPOSE"
    INFORM = "INFORM"
    FAILURE = "FAILURE"


# -----------------------------
# 1. USERS
# -----------------------------

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True
    )
    full_name: Mapped[str] = mapped_column(
        String(150), nullable=False
    )
    email: Mapped[str] = mapped_column(
        String(255), unique=True, index=True, nullable=False
    )
    password_hash: Mapped[str] = mapped_column(
        String(255), nullable=False
    )
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role"),
        default=UserRole.ATTENDEE,
        nullable=False
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


# -----------------------------
# 2. VENUES
# -----------------------------

class Venue(Base):
    __tablename__ = "venues"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True
    )
    name: Mapped[str] = mapped_column(
        String(200), nullable=False
    )
    location: Mapped[str] = mapped_column(
        String(255), nullable=False
    )
    capacity: Mapped[int] = mapped_column(
        Integer, nullable=False
    )
    description: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    image_url: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )
    hourly_hire_rate: Mapped[float] = mapped_column(
        Numeric(12, 2), nullable=False
    )
    is_open_for_hire: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )

    __table_args__ = (
        CheckConstraint("capacity > 0", name="ck_venue_capacity"),
        CheckConstraint(
            "hourly_hire_rate >= 0",
            name="ck_venue_rate"
        ),
    )


# -----------------------------
# 3. EVENTS
# -----------------------------

class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True
    )
    title: Mapped[str] = mapped_column(
        String(200), nullable=False
    )
    category: Mapped[str] = mapped_column(
        String(100), nullable=False
    )
    venue_id: Mapped[int] = mapped_column(
        ForeignKey("venues.id"), nullable=False
    )
    organiser_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    start_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    end_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    description: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    image_url: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )
    status: Mapped[EventStatus] = mapped_column(
        Enum(EventStatus, name="event_status"),
        default=EventStatus.DRAFT,
        nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )

    __table_args__ = (
        CheckConstraint(
            "end_time > start_time",
            name="ck_event_time"
        ),
        Index("ix_event_venue_time", "venue_id", "start_time"),
    )


# -----------------------------
# 4. TICKET CATEGORIES
# -----------------------------

class TicketCategory(Base):
    __tablename__ = "ticket_categories"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True
    )
    event_id: Mapped[int] = mapped_column(
        ForeignKey("events.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(
        String(100), nullable=False
    )
    price: Mapped[float] = mapped_column(
        Numeric(12, 2), nullable=False
    )
    quantity: Mapped[int] = mapped_column(
        Integer, nullable=False
    )
    sold_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "event_id", "name",
            name="uq_event_ticket_category"
        ),
        CheckConstraint("price >= 0", name="ck_ticket_price"),
        CheckConstraint("quantity >= 0", name="ck_ticket_quantity"),
        CheckConstraint(
            "sold_count >= 0 AND sold_count <= quantity",
            name="ck_ticket_sold_count"
        ),
    )


# -----------------------------
# 5. BOOKINGS
# -----------------------------

class Booking(Base):
    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True
    )
    booking_reference: Mapped[str] = mapped_column(
        String(64), unique=True, default=new_uuid,
        nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    event_id: Mapped[int] = mapped_column(
        ForeignKey("events.id"), nullable=False
    )
    ticket_category_id: Mapped[int] = mapped_column(
        ForeignKey("ticket_categories.id"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(
        Integer, nullable=False
    )
    total_amount: Mapped[float] = mapped_column(
        Numeric(12, 2), nullable=False
    )
    refund_amount: Mapped[float] = mapped_column(
        Numeric(12, 2), default=0, nullable=False
    )
    status: Mapped[BookingStatus] = mapped_column(
        Enum(BookingStatus, name="booking_status"),
        default=BookingStatus.PENDING,
        nullable=False
    )
    created_at: Mapped[datetime] =  mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_booking_quantity"),
        CheckConstraint("total_amount >= 0", name="ck_booking_total"),
        CheckConstraint("refund_amount >= 0", name="ck_booking_refund"),
    )


# -----------------------------
# 6. TICKETS
# -----------------------------

class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True
    )
    booking_id: Mapped[int] = mapped_column(
        ForeignKey("bookings.id"), nullable=False
    )
    event_id: Mapped[int] = mapped_column(
        ForeignKey("events.id"), nullable=False
    )
    ticket_category_id: Mapped[int] = mapped_column(
        ForeignKey("ticket_categories.id"), nullable=False
    )
    qr_token: Mapped[str] = mapped_column(
        String(128), unique=True, index=True,
        nullable=False
    )
    status: Mapped[TicketStatus] = mapped_column(
        Enum(TicketStatus, name="ticket_status"),
        default=TicketStatus.VALID,
        nullable=False
    )
    checked_in_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    checked_in_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    scan_attempts: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )

    __table_args__ = (
        CheckConstraint(
            "scan_attempts >= 0",
            name="ck_ticket_scan_attempts"
        ),
    )


# -----------------------------
# 7. SIMULATED PAYMENTS
# -----------------------------

class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True
    )
    booking_id: Mapped[int] = mapped_column(
        ForeignKey("bookings.id"), nullable=False
    )
    payment_reference: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False
    )
    amount: Mapped[float] = mapped_column(
        Numeric(12, 2), nullable=False
    )
    refunded_amount: Mapped[float] = mapped_column(
        Numeric(12, 2), default=0, nullable=False
    )
    status: Mapped[PaymentStatus] = mapped_column(
        Enum(PaymentStatus, name="payment_status"),
        default=PaymentStatus.SUCCESS,
        nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )

    __table_args__ = (
        CheckConstraint("amount >= 0", name="ck_payment_amount"),
        CheckConstraint(
            "refunded_amount >= 0 AND refunded_amount <= amount",
            name="ck_payment_refund"
        ),
    )


# -----------------------------
# 8. PRIVATE VENUE HIRE
# -----------------------------

class VenueHireRequest(Base):
    __tablename__ = "venue_hire_requests"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    venue_id: Mapped[int] = mapped_column(
        ForeignKey("venues.id"), nullable=False
    )
    start_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    end_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    purpose: Mapped[str] = mapped_column(
        Text, nullable=False
    )
    guest_count: Mapped[int] = mapped_column(
        Integer, nullable=False
    )
    quoted_price: Mapped[float | None] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    status: Mapped[HireStatus] = mapped_column(
        Enum(HireStatus, name="hire_status"),
        default=HireStatus.PENDING,
        nullable=False
    )
    decision_reason: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    alternatives: Mapped[list | None] = mapped_column(
        JSON, nullable=True
    )
    reviewed_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )

    __table_args__ = (
        CheckConstraint(
            "end_time > start_time",
            name="ck_hire_time"
        ),
        CheckConstraint(
            "guest_count > 0",
            name="ck_hire_guests"
        ),
        CheckConstraint(
            "quoted_price IS NULL OR quoted_price >= 0",
            name="ck_hire_price"
        ),
        Index("ix_hire_venue_time", "venue_id", "start_time"),
    )


# -----------------------------
# 9. WAITLIST ENTRIES
# -----------------------------

class WaitlistEntry(Base):
    __tablename__ = "waitlist_entries"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    event_id: Mapped[int] = mapped_column(
        ForeignKey("events.id"), nullable=False
    )
    ticket_category_id: Mapped[int] = mapped_column(
        ForeignKey("ticket_categories.id"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(
        Integer, default=1, nullable=False
    )
    status: Mapped[WaitlistStatus] = mapped_column(
        Enum(WaitlistStatus, name="waitlist_status"),
        default=WaitlistStatus.WAITING,
        nullable=False
    )
    offered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    offer_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    hold_token: Mapped[str | None] = mapped_column(
        String(128), unique=True, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )

    __table_args__ = (
        CheckConstraint(
            "quantity > 0",
            name="ck_waitlist_quantity"
        ),
        Index(
            "ix_waitlist_queue",
            "ticket_category_id", "status", "created_at"
        ),
    )


# -----------------------------
# 10. NOTIFICATIONS
# -----------------------------

class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    title: Mapped[str] = mapped_column(
        String(200), nullable=False
    )
    message: Mapped[str] = mapped_column(
        Text, nullable=False
    )
    is_read: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    conversation_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


# -----------------------------
# 11. AGENT MESSAGE LOG
# -----------------------------

class AgentMessage(Base):
    __tablename__ = "agent_messages"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True
    )
    message_id: Mapped[str] = mapped_column(
        String(64), unique=True, default=new_uuid,
        nullable=False
    )
    conversation_id: Mapped[str] = mapped_column(
        String(64), index=True, nullable=False
    )
    sender: Mapped[str] = mapped_column(
        String(100), nullable=False
    )
    receiver: Mapped[str] = mapped_column(
        String(100), nullable=False
    )
    performative: Mapped[MessagePerformative] = mapped_column(
        Enum(
            MessagePerformative,
            name="message_performative"
        ),
        nullable=False
    )
    content: Mapped[dict] = mapped_column(
        JSON, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


# -----------------------------
# 12. PERSISTENT AGENT STATE
# -----------------------------

class AgentState(Base):
    __tablename__ = "agent_states"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True
    )
    agent_name: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False
    )
    state_data: Mapped[dict] = mapped_column(
        JSON, default=dict, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now
    )


# -----------------------------
# 13. AGENT INBOX
# -----------------------------

class AgentInbox(Base):
    __tablename__ = "agent_inbox"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True
    )
    message_id: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False
    )
    receiver: Mapped[str] = mapped_column(
        String(100), nullable=False
    )
    payload: Mapped[dict] = mapped_column(
        JSON, nullable=False
    )
    processed: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index(
            "ix_agent_inbox_pending",
            "receiver", "processed"
        ),
    )


# -----------------------------
# 14. EVENT STAFF ASSIGNMENTS
# -----------------------------

class EventStaffAssignment(Base):
    __tablename__ = "event_staff_assignments"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    event_id: Mapped[int] = mapped_column(
        ForeignKey("events.id"),
        nullable=False,
    )

    staff_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
    )

    assigned_by: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
    )

    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "event_id",
            "staff_user_id",
            name="uq_event_staff_assignment",
        ),
        Index(
            "ix_event_staff_staff_user",
            "staff_user_id",
        ),
    )
