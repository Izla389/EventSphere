import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import User, Venue
from app.models.models import UserRole
from app.security import hash_password


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine)

    def override_get_db():
        with TestingSession() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app, follow_redirects=False) as test_client:
        test_client.testing_session = TestingSession
        yield test_client

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def get_csrf(client, url):
    response = client.get(url)
    assert response.status_code == 200

    match = re.search(
        r'name="csrf_token"\s+value="([^"]+)"',
        response.text,
    )

    assert match is not None
    return match.group(1)


def login_as(client, role):
    email = f"{role.value}@example.com"
    password = "StrongPassword123!"

    with client.testing_session() as db:
        db.add(
            User(
                full_name=f"Test {role.value}",
                email=email,
                password_hash=hash_password(password),
                role=role,
                is_active=True,
            )
        )
        db.commit()

    csrf = get_csrf(client, "/login")

    response = client.post(
        "/login",
        data={
            "email": email,
            "password": password,
            "csrf_token": csrf,
        },
    )

    assert response.status_code == 303


def venue_data(csrf_token, **overrides):
    data = {
        "name": "Grand Conference Hall",
        "location": "Kandy",
        "capacity": "500",
        "description": "Conference and workshop venue",
        "image_url": "",
        "hourly_hire_rate": "15000.00",
        "is_open_for_hire": "true",
        "csrf_token": csrf_token,
    }
    data.update(overrides)
    return data


def create_test_venue(client):
    csrf = get_csrf(client, "/admin/venues/new")
    return client.post(
        "/admin/venues/new",
        data=venue_data(csrf),
    )


def test_admin_can_create_venue(client):
    login_as(client, UserRole.ADMIN)

    response = create_test_venue(client)

    assert response.status_code == 303
    assert response.headers["location"].startswith("/admin/venues/")

    with client.testing_session() as db:
        venue = db.query(Venue).one()
        assert venue.name == "Grand Conference Hall"
        assert venue.capacity == 500


def test_admin_can_view_venue(client):
    login_as(client, UserRole.ADMIN)
    create_test_venue(client)

    response = client.get("/admin/venues/")

    assert response.status_code == 200
    assert "Grand Conference Hall" in response.text


def test_admin_can_update_venue(client):
    login_as(client, UserRole.ADMIN)
    create_test_venue(client)

    with client.testing_session() as db:
        venue_id = db.query(Venue).one().id

    csrf = get_csrf(client, f"/admin/venues/{venue_id}/edit")

    response = client.post(
        f"/admin/venues/{venue_id}/edit",
        data=venue_data(
            csrf,
            capacity="600",
            hourly_hire_rate="18000.00",
        ),
    )

    assert response.status_code == 303

    with client.testing_session() as db:
        venue = db.get(Venue, venue_id)
        assert venue.capacity == 600
        assert str(venue.hourly_hire_rate) == "18000.00"


def test_admin_can_delete_venue(client):
    login_as(client, UserRole.ADMIN)
    create_test_venue(client)

    with client.testing_session() as db:
        venue_id = db.query(Venue).one().id

    csrf = get_csrf(client, f"/admin/venues/{venue_id}")

    response = client.post(
        f"/admin/venues/{venue_id}/delete",
        data={"csrf_token": csrf},
    )

    assert response.status_code == 303

    with client.testing_session() as db:
        assert db.get(Venue, venue_id) is None


def test_invalid_capacity_rejected(client):
    login_as(client, UserRole.ADMIN)

    csrf = get_csrf(client, "/admin/venues/new")

    response = client.post(
        "/admin/venues/new",
        data=venue_data(csrf, capacity="0"),
    )

    assert response.status_code == 400

    with client.testing_session() as db:
        assert db.query(Venue).count() == 0


def test_negative_price_rejected(client):
    login_as(client, UserRole.ADMIN)

    csrf = get_csrf(client, "/admin/venues/new")

    response = client.post(
        "/admin/venues/new",
        data=venue_data(csrf, hourly_hire_rate="-100"),
    )

    assert response.status_code == 400


def test_csrf_required_for_creation(client):
    login_as(client, UserRole.ADMIN)

    response = client.post(
        "/admin/venues/new",
        data=venue_data("invalid-token"),
    )

    assert response.status_code == 403


def test_attendee_cannot_manage_venues(client):
    login_as(client, UserRole.ATTENDEE)

    response = client.get("/admin/venues/")
    assert response.status_code == 403

    response = client.get("/admin/venues/new")
    assert response.status_code == 403


def test_staff_cannot_manage_venues(client):
    login_as(client, UserRole.STAFF)

    response = client.get("/admin/venues/")
    assert response.status_code == 403


def test_anonymous_user_cannot_manage_venues(client):
    response = client.get("/admin/venues/")
    assert response.status_code == 401