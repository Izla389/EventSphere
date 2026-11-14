
from datetime import datetime, timezone

from fastapi import (
    APIRouter,
    Depends,
    Form,
    HTTPException,
    Request,
)
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.booking_validation import (
    BookingValidationError,
    get_available_tickets,
    reserve_booking,
    validate_event_bookable,
)
from app.database import get_db
from app.dependencies import require_role
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
from app.security import (
    create_csrf_token,
    verify_csrf_token,
)


templates = Jinja2Templates(directory="app/templates")

# Public event browsing
router = APIRouter(tags=["Attendee Events"])

# Attendee-only booking history
bookings_router = APIRouter(
    prefix="/my-bookings",
    tags=["Attendee Bookings"],
    dependencies=[
        Depends(require_role(UserRole.ATTENDEE))
    ],
)


def utc_now():
    return datetime.now(timezone.utc)


def get_published_event(
    db: Session,
    event_id: int,
) -> Event:
    event = db.get(Event, event_id)

    if event is None or event.status != EventStatus.PUBLISHED:
        raise HTTPException(
            status_code=404,
            detail="Published event not found.",
        )

    return event


def get_attendee_booking(
    db: Session,
    booking_id: int,
    user_id: int,
) -> Booking:
    booking = db.scalar(
        select(Booking).where(
            Booking.id == booking_id,
            Booking.user_id == user_id,
        )
    )

    if booking is None:
        raise HTTPException(
            status_code=404,
            detail="Booking not found.",
        )

    return booking


def booking_redirect(booking_id: int):
    return RedirectResponse(
        url=f"/my-bookings/{booking_id}",
        status_code=303,
    )


def booking_form_response(
    request: Request,
    db: Session,
    event: Event,
    *,
    error=None,
    selected_category_id=None,
    quantity="1",
    status_code=200,
):
    categories = db.scalars(
        select(TicketCategory)
        .where(TicketCategory.event_id == event.id)
        .order_by(TicketCategory.id)
    ).all()

    venue = db.get(Venue, event.venue_id)

    return templates.TemplateResponse(
        request=request,
        name="attendee_booking_form.html",
        context={
            "event": event,
            "venue": venue,
            "categories": categories,
            "available": {
                category.id: get_available_tickets(category)
                for category in categories
            },
            "error": error,
            "selected_category_id": selected_category_id,
            "quantity": quantity,
            "csrf_token": create_csrf_token(request),
        },
        status_code=status_code,
    )


# ----------------------------------------------
# PUBLIC: Browse published upcoming events
# ----------------------------------------------

@router.get(
    "/events/",
    response_class=HTMLResponse,
)
def browse_events(
    request: Request,
    db: Session = Depends(get_db),
):
    events = db.scalars(
        select(Event)
        .where(
            Event.status == EventStatus.PUBLISHED,
            Event.start_time > utc_now(),
        )
        .order_by(Event.start_time)
    ).all()

    venues = {
        venue.id: venue
        for venue in db.scalars(select(Venue)).all()
    }

    return templates.TemplateResponse(
        request=request,
        name="attendee_events_list.html",
        context={
            "events": events,
            "venues": venues,
        },
    )


# ----------------------------------------------
# PUBLIC: View published event details
# ----------------------------------------------

@router.get(
    "/events/{event_id}",
    response_class=HTMLResponse,
)
def attendee_event_detail(
    event_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    event = get_published_event(db, event_id)

    venue = db.get(Venue, event.venue_id)

    categories = db.scalars(
        select(TicketCategory)
        .where(TicketCategory.event_id == event_id)
        .order_by(TicketCategory.id)
    ).all()

    return templates.TemplateResponse(
        request=request,
        name="attendee_event_detail.html",
        context={
            "event": event,
            "venue": venue,
            "categories": categories,
            "available": {
                category.id: get_available_tickets(category)
                for category in categories
            },
            "can_book": (
                event.start_time.replace(tzinfo=timezone.utc)
                if event.start_time.tzinfo is None
                else event.start_time
            ) > utc_now(),
        },
    )


# ----------------------------------------------
# ATTENDEE: Display booking form
# ----------------------------------------------

@router.get(
    "/events/{event_id}/book",
    response_class=HTMLResponse,
)
def new_booking_form(
    event_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_role(UserRole.ATTENDEE)
    ),
):
    event = get_published_event(db, event_id)

    try:
        validate_event_bookable(event)
    except BookingValidationError as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc

    return booking_form_response(
        request,
        db,
        event,
    )


# ----------------------------------------------
# ATTENDEE: Create pending reservation
# ----------------------------------------------

@router.post("/events/{event_id}/book")
def create_booking(
    event_id: int,
    request: Request,
    ticket_category_id: int = Form(...),
    quantity: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_role(UserRole.ATTENDEE)
    ),
):
    verify_csrf_token(request, csrf_token)

    try:
        booking = reserve_booking(
            db,
            user_id=current_user.id,
            event_id=event_id,
            ticket_category_id=ticket_category_id,
            quantity=quantity,
        )

        booking_id = booking.id

        # Booking and inventory are committed together.
        db.commit()

        return booking_redirect(booking_id)

    except BookingValidationError as exc:
        db.rollback()

        event = get_published_event(db, event_id)

        return booking_form_response(
            request,
            db,
            event,
            error=str(exc),
            selected_category_id=ticket_category_id,
            quantity=quantity,
            status_code=400,
        )

    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Unable to save this booking.",
        ) from exc

    except SQLAlchemyError:
        db.rollback()
        raise


# ----------------------------------------------
# ATTENDEE: Booking history
# ----------------------------------------------

@bookings_router.get(
    "/",
    response_class=HTMLResponse,
)
def my_bookings(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_role(UserRole.ATTENDEE)
    ),
):
    bookings = db.scalars(
        select(Booking)
        .where(Booking.user_id == current_user.id)
        .order_by(Booking.created_at.desc())
    ).all()

    events = {
        event.id: event
        for event in db.scalars(select(Event)).all()
    }

    return templates.TemplateResponse(
        request=request,
        name="attendee_bookings_list.html",
        context={
            "bookings": bookings,
            "events": events,
        },
    )


# ----------------------------------------------
# ATTENDEE: Booking details
# ----------------------------------------------

@bookings_router.get(
    "/{booking_id}",
    response_class=HTMLResponse,
)
def my_booking_detail(
    booking_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_role(UserRole.ATTENDEE)
    ),
):
    booking = get_attendee_booking(
        db,
        booking_id,
        current_user.id,
    )

    event = db.get(Event, booking.event_id)

    category = db.get(
        TicketCategory,
        booking.ticket_category_id,
    )

    return templates.TemplateResponse(
        request=request,
        name="attendee_booking_detail.html",
        context={
            "booking": booking,
            "event": event,
            "category": category,
            "csrf_token": create_csrf_token(request),
        },
    )


# ----------------------------------------------
# ATTENDEE: Cancel a pending reservation
# ----------------------------------------------

@bookings_router.post("/{booking_id}/cancel")
def cancel_pending_booking(
    booking_id: int,
    request: Request,
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_role(UserRole.ATTENDEE)
    ),
):
    verify_csrf_token(request, csrf_token)

    try:
        # Identify the booking and its event.
        original = get_attendee_booking(
            db,
            booking_id,
            current_user.id,
        )

        # Always lock the event first.
        event = db.scalar(
            select(Event)
            .where(Event.id == original.event_id)
            .with_for_update()
        )

        if event is None:
            raise HTTPException(
                status_code=404,
                detail="Event not found.",
            )

        # Lock this booking to serialize cancellation attempts.
        booking = db.scalar(
            select(Booking)
            .where(
                Booking.id == booking_id,
                Booking.user_id == current_user.id,
            )
            .with_for_update()
        )

        if booking is None:
            raise HTTPException(
                status_code=404,
                detail="Booking not found.",
            )

        if booking.status != BookingStatus.PENDING:
            raise HTTPException(
                status_code=409,
                detail="Only pending bookings can be cancelled.",
            )

        # Lock inventory before releasing the reservation.
        category = db.scalar(
            select(TicketCategory)
            .where(
                TicketCategory.id == booking.ticket_category_id,
                TicketCategory.event_id == booking.event_id,
            )
            .with_for_update()
        )

        if category is None:
            raise HTTPException(
                status_code=409,
                detail="Ticket category not found.",
            )

        if category.sold_count < booking.quantity:
            raise HTTPException(
                status_code=409,
                detail="Ticket inventory is inconsistent.",
            )

        category.sold_count -= booking.quantity
        booking.status = BookingStatus.CANCELLED
        booking.cancelled_at = utc_now()

        db.commit()

        return booking_redirect(booking_id)

    except HTTPException:
        db.rollback()
        raise

    except SQLAlchemyError:
        db.rollback()
        raise
