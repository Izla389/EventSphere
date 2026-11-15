
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
from app.database import get_db
from app.routers.auth import router as auth_router
from app.routers.venues import router as venues_router
from app.routers import events
from app.routers import attendee
from app.routers import checkin
from app.routers import staff_dashboard
from app.routers import staff_assignments
from app.routers import attendance_reports


app = FastAPI(
    title="EventSphere",
    description="Agent-Based Venue Booking and Digital Ticketing Platform",
    version="1.0.0",
)


# Secure, signed cookie-based sessions
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.SECRET_KEY,
    session_cookie="eventsphere_session",
    max_age=60 * 60 * 8,
    same_site="lax",
    https_only=settings.SESSION_HTTPS_ONLY,
)


# Authentication routes
app.include_router(auth_router)

# Admin venue and event management
app.include_router(venues_router)
app.include_router(events.router)

# Attendee routes
app.include_router(attendee.router)
app.include_router(attendee.bookings_router)

# Staff routes
app.include_router(checkin.router)
app.include_router(staff_dashboard.router)

# Admin staff assignment management
app.include_router(staff_assignments.router)

# Admin attendance reports
app.include_router(attendance_reports.router)


@app.get("/")
def home():
    return RedirectResponse(url="/login")


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "application": "EventSphere",
    }


@app.get("/db-check")
def check_database(db: Session = Depends(get_db)):
    try:
        result = db.execute(
            text("SELECT current_database()")
        ).scalar_one()

        return {
            "status": "connected",
            "database": result,
            "message": "PostgreSQL connection successful",
        }

    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Database connection failed",
        )
