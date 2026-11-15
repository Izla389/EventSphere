
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.models import (
    Event,
    EventStaffAssignment,
    EventStatus,
    User,
    UserRole,
    Venue,
)
from app.security import hash_password


PASSWORD = "StrongPassword123!"


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    Base.metadata.create_all(bind=engine)

    TestingSession = sessionmaker(
        bind=engine,
        expire_on_commit=False,
    )

    def override_get_db():
        with TestingSession() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db

    try:
        with TestClient(
            app,
            follow_redirects=False,
        ) as test_client:
            test_client.testing_session = TestingSession
            yield test_client
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()



def create_user(db, role, email):
    user = User(
        full_name=f"Test {role.value}",
        email=email,
        password_hash=hash_password(PASSWORD),
        role=role,
        is_active=True,
    )

    db.add(user)
    db.flush()

    return user

# ----------------------------------------------
# Test data
# ----------------------------------------------

@pytest.fixture
def assignment_data(client):
    with client.testing_session() as db:
        admin = create_user(
            db, UserRole.ADMIN, "admin@assignment.test"
        )
        staff = create_user(
            db, UserRole.STAFF, "staff@assignment.test"
        )
        attendee = create_user(
            db, UserRole.ATTENDEE, "attendee@assignment.test"
        )

        venue = Venue(
            name="Staff Assignment Test Hall",
            location="Colombo",
            capacity=100,
            description="Staff assignment testing",
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
            title="Staff Assignment Test Event",
            category="Workshop",
            description="Assignment testing",
            venue_id=venue.id,
            organiser_id=admin.id,
            start_time=start,
            end_time=start + timedelta(hours=3),
            status=EventStatus.PUBLISHED,
        )
        db.add(event)
        db.flush()

        data = {
            "admin_id": admin.id,
            "staff_id": staff.id,
            "attendee_id": attendee.id,
            "event_id": event.id,
        }

        db.commit()

    return data


# ----------------------------------------------
# Login helper
# ----------------------------------------------

def login(client, email):
    response = client.get("/login")
    assert response.status_code == 200

    match = re.search(
        r'name="csrf_token"\s+value="([^"]+)"',
        response.text,
    )
    assert match is not None

    response = client.post(
        "/login",
        data={
            "email": email,
            "password": PASSWORD,
            "csrf_token": match.group(1),
        },
    )

    assert response.status_code == 303, response.text


def get_csrf(client):
    response = client.get("/admin/staff-assignments/")
    assert response.status_code == 200

    match = re.search(
        r'name="csrf_token"\s+value="([^"]+)"',
        response.text,
    )
    assert match is not None

    return match.group(1)


def submit_assignment(client, data, csrf_token=None):
    if csrf_token is None:
        csrf_token = get_csrf(client)

    return client.post(
        "/admin/staff-assignments/assign",
        data={
            "event_id": str(data["event_id"]),
            "staff_user_id": str(data["staff_id"]),
            "csrf_token": csrf_token,
        },
    )


# ----------------------------------------------
# Test 1 — Anonymous access
# ----------------------------------------------

def test_anonymous_cannot_open_assignment_page(client):
    response = client.get("/admin/staff-assignments/")
    assert response.status_code == 401


# ----------------------------------------------
# Test 2 — Attendee access
# ----------------------------------------------

def test_attendee_cannot_open_assignment_page(
    client, assignment_data
):
    login(client, "attendee@assignment.test")

    response = client.get("/admin/staff-assignments/")
    assert response.status_code == 403


# ----------------------------------------------
# Test 3 — Staff access
# ----------------------------------------------

def test_staff_cannot_open_assignment_page(
    client, assignment_data
):
    login(client, "staff@assignment.test")

    response = client.get("/admin/staff-assignments/")
    assert response.status_code == 403


# ----------------------------------------------
# Test 4 — Admin access
# ----------------------------------------------

def test_admin_can_open_assignment_page(
    client, assignment_data
):
    login(client, "admin@assignment.test")

    response = client.get("/admin/staff-assignments/")

    assert response.status_code == 200
    assert "Event Staff Assignments" in response.text
    assert "Staff Assignment Test Event" in response.text


# ----------------------------------------------
# Test 5 — Successful assignment
# ----------------------------------------------

def test_admin_can_assign_staff(
    client, assignment_data
):
    login(client, "admin@assignment.test")

    response = submit_assignment(client, assignment_data)

    assert response.status_code == 303
    assert "success=assigned" in response.headers["location"]

    with client.testing_session() as db:
        assignment = db.scalar(
            select(EventStaffAssignment).where(
                EventStaffAssignment.event_id
                == assignment_data["event_id"],
                EventStaffAssignment.staff_user_id
                == assignment_data["staff_id"],
            )
        )

        assert assignment is not None
        assert assignment.assigned_by == assignment_data["admin_id"]


# ----------------------------------------------
# Test 6 — Duplicate assignment
# ----------------------------------------------

def test_duplicate_assignment_is_rejected(
    client, assignment_data
):
    login(client, "admin@assignment.test")

    first = submit_assignment(client, assignment_data)
    second = submit_assignment(client, assignment_data)

    assert first.status_code == 303
    assert second.status_code == 303
    assert "error=" in second.headers["location"]

    with client.testing_session() as db:
        assignments = db.scalars(
            select(EventStaffAssignment).where(
                EventStaffAssignment.event_id
                == assignment_data["event_id"],
                EventStaffAssignment.staff_user_id
                == assignment_data["staff_id"],
            )
        ).all()

        assert len(assignments) == 1


# ----------------------------------------------
# Test 7 — Invalid CSRF
# ----------------------------------------------

def test_invalid_csrf_rejects_assignment(
    client, assignment_data
):
    login(client, "admin@assignment.test")

    response = submit_assignment(
        client,
        assignment_data,
        csrf_token="invalid-token",
    )

    assert response.status_code == 403

    with client.testing_session() as db:
        assignments = db.scalars(
            select(EventStaffAssignment)
        ).all()

        assert len(assignments) == 0


# ----------------------------------------------
# Test 8 — Attendee cannot assign staff
# ----------------------------------------------

def test_attendee_cannot_assign_staff(
    client, assignment_data
):
    login(client, "attendee@assignment.test")

    response = client.post(
        "/admin/staff-assignments/assign",
        data={
            "event_id": str(assignment_data["event_id"]),
            "staff_user_id": str(assignment_data["staff_id"]),
            "csrf_token": "invalid-token",
        },
    )

    assert response.status_code == 403


# ----------------------------------------------
# Test 9 — Admin can remove assignment
# ----------------------------------------------

def test_admin_can_remove_assignment(
    client, assignment_data
):
    login(client, "admin@assignment.test")

    submit_assignment(client, assignment_data)

    with client.testing_session() as db:
        assignment = db.scalar(
            select(EventStaffAssignment)
        )
        assignment_id = assignment.id

    response = client.post(
        "/admin/staff-assignments/remove",
        data={
            "assignment_id": str(assignment_id),
            "csrf_token": get_csrf(client),
        },
    )

    assert response.status_code == 303
    assert "success=removed" in response.headers["location"]

    with client.testing_session() as db:
        assert db.get(
            EventStaffAssignment,
            assignment_id,
        ) is None


# ----------------------------------------------
# Test 10 — Cannot assign attendee as staff
# ----------------------------------------------

def test_cannot_assign_attendee_as_staff(
    client, assignment_data
):
    login(client, "admin@assignment.test")

    response = client.post(
        "/admin/staff-assignments/assign",
        data={
            "event_id": str(assignment_data["event_id"]),
            "staff_user_id": str(assignment_data["attendee_id"]),
            "csrf_token": get_csrf(client),
        },
    )

    assert response.status_code == 303
    assert "error=" in response.headers["location"]

    with client.testing_session() as db:
        assert db.scalars(
            select(EventStaffAssignment)
        ).all() == []
