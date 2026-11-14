
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from threading import Barrier

import pytest
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.booking_validation import (
    BookingValidationError,
    reserve_booking,
)
from app.config import settings
from app.database import Base
from app.models.models import (
    Booking,
    BookingStatus,
    Event,
    EventStatus,
    TicketCategory,
    User,
    UserRole,
    Venue,
)
from app.security import hash_password


# This test must be enabled explicitly.
# Normal pytest runs will skip it.
RUN_POSTGRES_TEST = (
    os.environ.get("RUN_POSTGRES_CONCURRENCY") == "1"
)


def get_test_engine():
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
                    "The test database already contains tables. "
                    "Use an empty, dedicated eventsphere_test database. "
                    "No tables have been changed."
                )

        return engine

    except Exception:
        engine.dispose()
        raise


@pytest.mark.skipif(
    not RUN_POSTGRES_TEST,
    reason="Requires RUN_POSTGRES_CONCURRENCY=1",
)
def test_last_ticket_cannot_be_oversold():
    engine = get_test_engine()

    # Only tables created by this test will be removed.
    schema_created = False

    try:
        Base.metadata.create_all(bind=engine)
        schema_created = True

        SessionFactory = sessionmaker(
            bind=engine,
            autoflush=False,
            expire_on_commit=False,
        )

        # --------------------------------------
        # Create isolated test data
        # --------------------------------------

        with SessionFactory() as db:
            admin = User(
                full_name="Concurrency Admin",
                email="concurrency-admin@example.com",
                password_hash=hash_password(
                    "StrongPassword123!"
                ),
                role=UserRole.ADMIN,
                is_active=True,
            )

            attendee_a = User(
                full_name="Attendee A",
                email="concurrency-a@example.com",
                password_hash=hash_password(
                    "StrongPassword123!"
                ),
                role=UserRole.ATTENDEE,
                is_active=True,
            )

            attendee_b = User(
                full_name="Attendee B",
                email="concurrency-b@example.com",
                password_hash=hash_password(
                    "StrongPassword123!"
                ),
                role=UserRole.ATTENDEE,
                is_active=True,
            )

            db.add_all([
                admin,
                attendee_a,
                attendee_b,
            ])
            db.flush()

            venue = Venue(
                name="Concurrency Test Venue",
                location="Test Location",
                capacity=10,
                description="Concurrency test",
                hourly_hire_rate=Decimal("1000.00"),
                is_open_for_hire=True,
            )

            db.add(venue)
            db.flush()

            start = (
                datetime.now(timezone.utc)
                + timedelta(days=30)
            ).replace(tzinfo=None)

            event = Event(
                title="Last Ticket Concurrency Test",
                category="Workshop",
                description="PostgreSQL locking test",
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
                name="Last Available Ticket",
                price=Decimal("1500.00"),
                quantity=1,
                sold_count=0,
            )

            db.add(category)
            db.flush()

            event_id = event.id
            category_id = category.id
            attendee_ids = [
                attendee_a.id,
                attendee_b.id,
            ]

            db.commit()

        # --------------------------------------
        # Two independent booking transactions
        # --------------------------------------

        start_barrier = Barrier(2, timeout=10)

        def attempt_booking(user_id):
            with SessionFactory() as db:
                try:
                    # Start both attempts together.
                    start_barrier.wait()

                    booking = reserve_booking(
                        db,
                        user_id=user_id,
                        event_id=event_id,
                        ticket_category_id=category_id,
                        quantity=1,
                    )

                    booking_id = booking.id
                    db.commit()

                    return ("success", booking_id)

                except BookingValidationError as exc:
                    db.rollback()
                    return ("rejected", str(exc))

                except Exception:
                    db.rollback()
                    raise

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(
                    attempt_booking,
                    attendee_id,
                )
                for attendee_id in attendee_ids
            ]

            results = [
                future.result(timeout=20)
                for future in futures
            ]

        print("\nConcurrent booking results:")
        for result in results:
            print(result)

        successful = [
            result
            for result in results
            if result[0] == "success"
        ]

        rejected = [
            result
            for result in results
            if result[0] == "rejected"
        ]

        # Exactly one transaction must succeed.
        assert len(successful) == 1
        assert len(rejected) == 1

        # --------------------------------------
        # Verify persisted PostgreSQL state
        # --------------------------------------

        with SessionFactory() as db:
            category = db.get(
                TicketCategory,
                category_id,
            )

            bookings = db.scalars(
                select(Booking).where(
                    Booking.event_id == event_id
                )
            ).all()

            assert category.quantity == 1
            assert category.sold_count == 1

            assert len(bookings) == 1

            assert (
                bookings[0].status
                == BookingStatus.PENDING
            )

            assert bookings[0].quantity == 1
            assert bookings[0].total_amount == Decimal(
                "1500.00"
            )

        print(
            "\nPASS: PostgreSQL prevented overselling."
        )

    finally:
        # Cleanup is limited to the dedicated database
        # after its empty-schema safety check.
        try:
            if schema_created:
                Base.metadata.drop_all(bind=engine)
        finally:
            engine.dispose()
