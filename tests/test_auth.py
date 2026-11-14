import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import User
from app.models.models import UserRole
from app.security import hash_password, verify_password

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

def csrf_from_page(client, url):
    response = client.get(url)
    assert response.status_code == 200

    match = re.search(
        r'name="csrf_token"\s+value="([^"]+)"',
        response.text,
    )
    assert match is not None
    return match.group(1)

def register_attendee(client):
    token = csrf_from_page(client, "/register")

    return client.post(
        "/register",
        data={
            "full_name": "Test Attendee",
            "email": "attendee@example.com",
            "password": "StrongPassword123!",
            "confirm_password": "StrongPassword123!",
            "csrf_token": token,
        },
    )

def test_password_hashing():
    password = "StrongPassword123!"
    hashed = hash_password(password)

    assert hashed != password
    assert verify_password(password, hashed)
    assert not verify_password("WrongPassword", hashed)

def test_registration_creates_attendee(client):
    response = register_attendee(client)

    assert response.status_code == 303
    assert response.headers["location"] == "/dashboard"

    with client.testing_session() as db:
        user = db.query(User).filter_by(
            email="attendee@example.com"
        ).one()

        assert user.role == UserRole.ATTENDEE
        assert user.password_hash != "StrongPassword123!"

def test_registration_rejects_missing_csrf(client):
    response = client.post(
        "/register",
        data={
            "full_name": "Invalid User",
            "email": "invalid@example.com",
            "password": "StrongPassword123!",
            "confirm_password": "StrongPassword123!",
            "csrf_token": "invalid-token",
        },
    )

    assert response.status_code == 403

def test_login_and_logout(client):
    register_attendee(client)

    dashboard = client.get("/dashboard")
    assert dashboard.status_code == 200
    assert "Test Attendee" in dashboard.text

    token = csrf_from_page(client, "/login")

    # Logout requires the current session's CSRF token.
    response = client.post(
        "/logout",
        data={"csrf_token": token},
    )
    assert response.status_code == 303

    assert client.get("/dashboard").status_code == 401

    token = csrf_from_page(client, "/login")

    login = client.post(
        "/login",
        data={
            "email": "attendee@example.com",
            "password": "StrongPassword123!",
            "csrf_token": token,
        },
    )

    assert login.status_code == 303
    assert client.get("/dashboard").status_code == 200

def test_attendee_cannot_access_admin(client):
    register_attendee(client)

    assert client.get("/admin").status_code == 403
    assert client.get("/staff").status_code == 403
    assert client.get("/attendee").status_code == 200

def test_admin_can_access_admin_only(client):
    with client.testing_session() as db:
        db.add(
            User(
                full_name="Test Admin",
                email="admin@example.com",
                password_hash=hash_password("AdminPassword123!"),
                role=UserRole.ADMIN,
                is_active=True,
            )
        )
        db.commit()

    token = csrf_from_page(client, "/login")

    response = client.post(
        "/login",
        data={
            "email": "admin@example.com",
            "password": "AdminPassword123!",
            "csrf_token": token,
        },
    )

    assert response.status_code == 303
    assert client.get("/admin").status_code == 200
    assert client.get("/staff").status_code == 403
    assert client.get("/attendee").status_code == 403