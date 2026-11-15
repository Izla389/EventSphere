
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from threading import Barrier

import pytest
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.database import Base
from app.models.models import (
    Booking,
    BookingStatus,
    Event,
    EventStatus,
    Payment,
    PaymentStatus,
    Ticket,
    TicketCategory,
    TicketStatus,
    User,
    UserRole,
    Venue,
)
from app.payment_service import (
    PaymentValidationError,
    confirm_simulated_payment,
)
from app.security import hash_password


# These tests are disabled during normal pytest runs.
RUN_POSTGRES_TEST = (
    os.environ.get("RUN_POSTGRES_PAYMENT_TESTS") == "1"
)

pytestmark = pytest.mark.skipif(
    not RUN_POSTGRES_TEST,
    reason="Requires RUN_POSTGRES_PAYMENT_TESTS=1",
)


def create_test_engine():
    main_url = make_url(settings.DATABASE_URL)

    if main_url.database == "eventsphere_test":
        raise RuntimeError(
            "Main DATABASE_URL must not point to the test database."
        )

    test_url = main_url.set(database="eventsphere_test")

    engine = create_engine(
        test_url,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 5},
    )

    try:
        with engine.connect() as connection:
            database_name = connection.execute(
                text("SELECT current_database()")
            ).scalar_one()

            if database_name != "eventsphere_test":
                raise RuntimeError(
                    "Safety check failed: wrong database."
                )

            existing_tables = inspect(
                connection
            ).get_table_names(schema="public")

            if existing_tables:
                raise RuntimeError(
                    "The test database is not empty. "
                    "No tables were changed."
                )

        return engine

    except Exception:
        engine.dispose()
        raise


@pytest.fixture(scope="module")
def payment_db():
    engine = create_test_engine()
    schema_created = False

    try:
        Base.metadata.create_all(bind=engine)
        schema_created = True

        SessionFactory = sessionmaker(
            bind=engine,
            autoflush=False,
            expire_on_commit=False,
        )

        yield SessionFactory

    finally:
        try:
            if schema_created:
                Base.metadata.drop_all(bind=engine)
        finally:
            engine.dispose()


@pytest.fixture
def booking_data(payment_db):
    """
    Create a new attendee, venue, event, category,
    and pending booking for each test.
    """

    with payment_db() as db:
        unique_id = os.urandom(8).hex()

        admin = User(
            full_name="Payment Test Admin",
            email=f"admin-{unique_id}@example.com",
            password_hash=hash_password("TestPassword123!"),
            role=UserRole.ADMIN,
            is_active=True,
        )

        attendee = User(
            full_name="Payment Test Attendee",
            email=f"attendee-{unique_id}@example.com",
            password_hash=hash_password("TestPassword123!"),
            role=UserRole.ATTENDEE,
            is_active=True,
        )

        db.add_all([admin, attendee])
        db.flush()

        venue = Venue(
            name=f"Payment Test Venue {unique_id}",
            location="Test Location",
            capacity=100,
            description="Payment testing",
            hourly_hire_rate=Decimal("1000.00"),
            is_open_for_hire=True,
        )

        db.add(venue)
        db.flush()

        start = (
            datetime.now(timezone.utc)
            + timedelta(days=30)
        )

        event = Event(
            title="Payment Test Event",
            category="Workshop",
            description="Payment testing",
            venue_id=venue.id,
            organiser_id=admin.id,
            start_time=start,
            end_time=start + timedelta(hours=2),
            status=EventStatus.PUBLISHED,
        )

        db.add(event)
        db.flush()

        category = TicketCategory(
            event_id=event.id,
            name="General Admission",
            price=Decimal("1500.00"),
            quantity=10,
            sold_count=2,
        )

        db.add(category)
        db.flush()

        booking = Booking(
            user_id=attendee.id,
            event_id=event.id,
            ticket_category_id=category.id,
            quantity=2,
            total_amount=Decimal("3000.00"),
            status=BookingStatus.PENDING,
        )

        db.add(booking)
        db.flush()

        data = {
            "booking_id": booking.id,
            "attendee_id": attendee.id,
            "event_id": event.id,
            "category_id": category.id,
        }

        db.commit()

        return data


# ---------------------------------------
# Test 1 — Successful payment
# ---------------------------------------

def test_successful_payment_creates_tickets(
    payment_db,
    booking_data,
):
    with payment_db() as db:
        payment, booking, tickets = (
            confirm_simulated_payment(
                db,
                booking_id=booking_data["booking_id"],
                user_id=booking_data["attendee_id"],
            )
        )

        assert payment.status == PaymentStatus.SUCCESS
        assert booking.status == BookingStatus.CONFIRMED
        assert len(tickets) == 2

        db.commit()

    with payment_db() as db:
        saved_booking = db.get(
            Booking,
            booking_data["booking_id"],
        )

        payments = db.scalars(
            select(Payment).where(
                Payment.booking_id == saved_booking.id
            )
        ).all()

        tickets = db.scalars(
            select(Ticket).where(
                Ticket.booking_id == saved_booking.id
            )
        ).all()

        assert saved_booking.status == BookingStatus.CONFIRMED
        assert len(payments) == 1
        assert len(tickets) == 2

        assert all(
            ticket.status == TicketStatus.VALID
            for ticket in tickets
        )

        tokens = [ticket.qr_token for ticket in tickets]
        assert len(set(tokens)) == 2


# ---------------------------------------
# Test 2 — Transaction rollback
# ---------------------------------------

def test_payment_rollback_removes_all_changes(
    payment_db,
    booking_data,
):
    with payment_db() as db:
        payment, booking, tickets = (
            confirm_simulated_payment(
                db,
                booking_id=booking_data["booking_id"],
                user_id=booking_data["attendee_id"],
            )
        )

        assert booking.status == BookingStatus.CONFIRMED
        assert len(tickets) == 2

        # Simulate a failure before committing.
        db.rollback()

    with payment_db() as db:
        saved_booking = db.get(
            Booking,
            booking_data["booking_id"],
        )

        payments = db.scalars(
            select(Payment).where(
                Payment.booking_id == saved_booking.id
            )
        ).all()

        tickets = db.scalars(
            select(Ticket).where(
                Ticket.booking_id == saved_booking.id
            )
        ).all()

        assert saved_booking.status == BookingStatus.PENDING
        assert len(payments) == 0
        assert len(tickets) == 0


# ---------------------------------------
# Test 3 — Duplicate payment rejection
# ---------------------------------------

def test_duplicate_payment_is_rejected(
    payment_db,
    booking_data,
):
    with payment_db() as db:
        confirm_simulated_payment(
            db,
            booking_id=booking_data["booking_id"],
            user_id=booking_data["attendee_id"],
        )

        db.commit()

    with payment_db() as db:
        with pytest.raises(
            PaymentValidationError,
            match="already been confirmed",
        ):
            confirm_simulated_payment(
                db,
                booking_id=booking_data["booking_id"],
                user_id=booking_data["attendee_id"],
            )

        db.rollback()

    with payment_db() as db:
        payments = db.scalars(
            select(Payment).where(
                Payment.booking_id == booking_data["booking_id"]
            )
        ).all()

        tickets = db.scalars(
            select(Ticket).where(
                Ticket.booking_id == booking_data["booking_id"]
            )
        ).all()

        assert len(payments) == 1
        assert len(tickets) == 2


# ---------------------------------------
# Test 4 — Concurrent payment protection
# ---------------------------------------

def test_concurrent_payments_do_not_duplicate_tickets(
    payment_db,
    booking_data,
):
    barrier = Barrier(2, timeout=10)

    def attempt_payment():
        with payment_db() as db:
            try:
                # Both threads begin before either payment.
                barrier.wait()

                payment, booking, tickets = (
                    confirm_simulated_payment(
                        db,
                        booking_id=booking_data["booking_id"],
                        user_id=booking_data["attendee_id"],
                    )
                )

                db.commit()

                return "success"

            except PaymentValidationError:
                db.rollback()
                return "rejected"

            except Exception:
                db.rollback()
                raise

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(attempt_payment)
            for _ in range(2)
        ]

        results = [
            future.result(timeout=20)
            for future in futures
        ]

    print("\nConcurrent payment results:", results)

    assert results.count("success") == 1
    assert results.count("rejected") == 1

    with payment_db() as db:
        booking = db.get(
            Booking,
            booking_data["booking_id"],
        )

        payments = db.scalars(
            select(Payment).where(
                Payment.booking_id == booking.id
            )
        ).all()

        tickets = db.scalars(
            select(Ticket).where(
                Ticket.booking_id == booking.id
            )
        ).all()

        assert booking.status == BookingStatus.CONFIRMED
        assert len(payments) == 1
        assert len(tickets) == 2

        tokens = [ticket.qr_token for ticket in tickets]
        assert len(set(tokens)) == 2
