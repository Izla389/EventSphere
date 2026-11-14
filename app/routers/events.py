
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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_role
from app.models.models import (
    Event,
    EventStatus,
    HireStatus,
    TicketCategory,
    UserRole,
    Venue,
)
from app.security import create_csrf_token, verify_csrf_token
from app.event_validation import (
    EventValidationError,
    check_ticket_capacity,
    check_venue_availability,
    validate_event,
    validate_ticket_category,
)


router = APIRouter(
    prefix="/admin/events",
    tags=["Event Management"],
    dependencies=[Depends(require_role(UserRole.ADMIN))],
)

templates = Jinja2Templates(directory="app/templates")


# --------------------------------------------------
# Helper functions
# --------------------------------------------------

def get_event_or_404(db: Session, event_id: int) -> Event:
    event = db.get(Event, event_id)

    if event is None:
        raise HTTPException(
            status_code=404,
            detail="Event not found",
        )

    return event


def get_category_or_404(
    db: Session,
    event_id: int,
    category_id: int,
) -> TicketCategory:
    category = db.scalar(
        select(TicketCategory).where(
            TicketCategory.id == category_id,
            TicketCategory.event_id == event_id,
        )
    )

    if category is None:
        raise HTTPException(
            status_code=404,
            detail="Ticket category not found",
        )

    return category


def lock_venue_or_404(db: Session, venue_id: int) -> Venue:
    """
    Lock the venue row for the duration of the transaction.

    On PostgreSQL, this serializes competing event scheduling
    and ticket allocation operations for the same venue.
    """
    venue = db.scalar(
        select(Venue)
        .where(Venue.id == venue_id)
        .with_for_update()
    )

    if venue is None:
        raise HTTPException(
            status_code=404,
            detail="Venue not found",
        )

    return venue


def lock_event_or_404(db: Session, event_id: int) -> Event:
    event = db.scalar(
        select(Event)
        .where(Event.id == event_id)
        .with_for_update()
    )

    if event is None:
        raise HTTPException(
            status_code=404,
            detail="Event not found",
        )

    return event


def require_draft(event: Event) -> None:
    if event.status != EventStatus.DRAFT:
        raise HTTPException(
            status_code=409,
            detail="Only draft events can be modified.",
        )


def redirect_to_event(event_id: int) -> RedirectResponse:
    return RedirectResponse(
        url=f"/admin/events/{event_id}",
        status_code=303,
    )


def render_event_form(
    request: Request,
    db: Session,
    *,
    event=None,
    error=None,
    form_data=None,
    status_code=200,
):
    venues = db.scalars(
        select(Venue).order_by(Venue.name)
    ).all()

    return templates.TemplateResponse(
        request=request,
        name="event_form.html",
        context={
            "event": event,
            "venues": venues,
            "error": error,
            "form_data": form_data,
            "csrf_token": create_csrf_token(request),
        },
        status_code=status_code,
    )


def render_category_form(
    request: Request,
    *,
    event,
    category=None,
    error=None,
    form_data=None,
    status_code=200,
):
    return templates.TemplateResponse(
        request=request,
        name="ticket_category_form.html",
        context={
            "event": event,
            "category": category,
            "error": error,
            "form_data": form_data,
            "csrf_token": create_csrf_token(request),
        },
        status_code=status_code,
    )


def event_form_values(
    title,
    category,
    venue_id,
    start_time,
    end_time,
    description,
    image_url,
):
    return {
        "title": title,
        "category": category,
        "venue_id": venue_id,
        "start_time": start_time,
        "end_time": end_time,
        "description": description,
        "image_url": image_url,
    }


def validate_event_values(form_data):
    return validate_event(
        title=form_data["title"],
        category=form_data["category"],
        start_time=form_data["start_time"],
        end_time=form_data["end_time"],
        description=form_data["description"],
        image_url=form_data["image_url"],
    )


def category_form_values(name, price, quantity):
    return {
        "name": name,
        "price": price,
        "quantity": quantity,
    }


def handle_database_integrity_error(db: Session, message: str):
    db.rollback()
    raise HTTPException(
        status_code=409,
        detail=message,
    )


# --------------------------------------------------
# Event listing
# --------------------------------------------------

@router.get("/", response_class=HTMLResponse)
def list_events(
    request: Request,
    db: Session = Depends(get_db),
):
    events = db.scalars(
        select(Event).order_by(Event.start_time.desc())
    ).all()

    venues = {
        venue.id: venue
        for venue in db.scalars(select(Venue)).all()
    }

    return templates.TemplateResponse(
        request=request,
        name="events_list.html",
        context={
            "events": events,
            "venues": venues,
        },
    )


# --------------------------------------------------
# Create event
# --------------------------------------------------

@router.get("/new", response_class=HTMLResponse)
def new_event_form(
    request: Request,
    db: Session = Depends(get_db),
):
    return render_event_form(request, db)


@router.post("/new")
def create_event(
    request: Request,
    title: str = Form(...),
    category: str = Form(...),
    venue_id: int = Form(...),
    start_time: str = Form(...),
    end_time: str = Form(...),
    description: str = Form(""),
    image_url: str = Form(""),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    verify_csrf_token(request, csrf_token)

    form_data = event_form_values(
        title,
        category,
        venue_id,
        start_time,
        end_time,
        description,
        image_url,
    )

    try:
        cleaned = validate_event_values(form_data)

        # Lock the venue before checking scheduling conflicts.
        lock_venue_or_404(db, venue_id)

        check_venue_availability(
            db=db,
            venue_id=venue_id,
            start_time=cleaned["start_time"],
            end_time=cleaned["end_time"],
        )

        # Authentication from Step 6 stores the user ID
        # in the signed session.
        organiser_id = request.session.get("user_id")

        if organiser_id is None:
            raise HTTPException(
                status_code=401,
                detail="Authentication required",
            )

        event = Event(
            **cleaned,
            venue_id=venue_id,
            organiser_id=int(organiser_id),
            status=EventStatus.DRAFT,
        )

        db.add(event)
        db.commit()
        db.refresh(event)

        return redirect_to_event(event.id)

    except EventValidationError as exc:
        db.rollback()
        return render_event_form(
            request,
            db,
            error=str(exc),
            form_data=form_data,
            status_code=400,
        )


# --------------------------------------------------
# View event
# --------------------------------------------------

@router.get("/{event_id}", response_class=HTMLResponse)
def view_event(
    event_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    event = get_event_or_404(db, event_id)
    venue = db.get(Venue, event.venue_id)

    categories = db.scalars(
        select(TicketCategory)
        .where(TicketCategory.event_id == event_id)
        .order_by(TicketCategory.id)
    ).all()

    return templates.TemplateResponse(
        request=request,
        name="event_detail.html",
        context={
            "event": event,
            "venue": venue,
            "categories": categories,
            "csrf_token": create_csrf_token(request),
        },
    )


# --------------------------------------------------
# Edit draft event
# --------------------------------------------------

@router.get("/{event_id}/edit", response_class=HTMLResponse)
def edit_event_form(
    event_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    event = get_event_or_404(db, event_id)
    require_draft(event)

    return render_event_form(
        request,
        db,
        event=event,
    )


@router.post("/{event_id}/edit")
def update_event(
    event_id: int,
    request: Request,
    title: str = Form(...),
    category: str = Form(...),
    venue_id: int = Form(...),
    start_time: str = Form(...),
    end_time: str = Form(...),
    description: str = Form(""),
    image_url: str = Form(""),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    verify_csrf_token(request, csrf_token)

    form_data = event_form_values(
        title,
        category,
        venue_id,
        start_time,
        end_time,
        description,
        image_url,
    )

    try:
        cleaned = validate_event_values(form_data)

        # Lock both the old and the new venue, in sorted
        # order, to reduce deadlock risk.
        original = get_event_or_404(db, event_id)

        for locked_venue_id in sorted(
            {original.venue_id, venue_id}
        ):
            lock_venue_or_404(db, locked_venue_id)

        event = lock_event_or_404(db, event_id)
        require_draft(event)

        check_venue_availability(
            db=db,
            venue_id=venue_id,
            start_time=cleaned["start_time"],
            end_time=cleaned["end_time"],
            exclude_event_id=event_id,
        )

        # Existing ticket allocations must fit the new venue.
        allocated = sum(
            ticket.quantity
            for ticket in db.scalars(
                select(TicketCategory).where(
                    TicketCategory.event_id == event_id
                )
            ).all()
        )

        new_venue = db.get(Venue, venue_id)

        if allocated > new_venue.capacity:
            raise EventValidationError(
                "The selected venue is too small for the "
                "existing ticket allocations."
            )

        for field, value in cleaned.items():
            setattr(event, field, value)

        event.venue_id = venue_id

        db.commit()

        return redirect_to_event(event_id)

    except EventValidationError as exc:
        db.rollback()

        event = get_event_or_404(db, event_id)

        return render_event_form(
            request,
            db,
            event=event,
            error=str(exc),
            form_data=form_data,
            status_code=400,
        )


# --------------------------------------------------
# Publish event
# --------------------------------------------------

@router.post("/{event_id}/publish")
def publish_event(
    event_id: int,
    request: Request,
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    verify_csrf_token(request, csrf_token)

    original = get_event_or_404(db, event_id)

    lock_venue_or_404(db, original.venue_id)

    event = lock_event_or_404(db, event_id)
    require_draft(event)

    categories = db.scalars(
        select(TicketCategory).where(
            TicketCategory.event_id == event_id
        )
    ).all()

    if not categories:
        raise HTTPException(
            status_code=409,
            detail="Add at least one ticket category before publishing.",
        )

    venue = db.get(Venue, event.venue_id)

    total_quantity = sum(
        ticket.quantity for ticket in categories
    )

    if total_quantity > venue.capacity:
        raise HTTPException(
            status_code=409,
            detail="Ticket allocation exceeds venue capacity.",
        )

    try:
        check_venue_availability(
            db=db,
            venue_id=event.venue_id,
            start_time=event.start_time,
            end_time=event.end_time,
            exclude_event_id=event.id,
        )
    except EventValidationError as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        )

    event.status = EventStatus.PUBLISHED
    db.commit()

    return redirect_to_event(event_id)


# --------------------------------------------------
# Cancel event
# --------------------------------------------------

@router.post("/{event_id}/cancel")
def cancel_event(
    event_id: int,
    request: Request,
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    verify_csrf_token(request, csrf_token)

    event = lock_event_or_404(db, event_id)

    if event.status == EventStatus.CANCELLED:
        raise HTTPException(
            status_code=409,
            detail="This event is already cancelled.",
        )

    event.status = EventStatus.CANCELLED
    db.commit()

    return redirect_to_event(event_id)


# --------------------------------------------------
# Delete draft event
# --------------------------------------------------

@router.post("/{event_id}/delete")
def delete_event(
    event_id: int,
    request: Request,
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    verify_csrf_token(request, csrf_token)

    event = lock_event_or_404(db, event_id)
    require_draft(event)

    # Draft events may contain unsold ticket categories.
    # Remove them before removing the event.
    categories = db.scalars(
        select(TicketCategory).where(
            TicketCategory.event_id == event_id
        )
    ).all()

    if any(ticket.sold_count > 0 for ticket in categories):
        raise HTTPException(
            status_code=409,
            detail="An event with sold tickets cannot be deleted.",
        )

    try:
        for ticket in categories:
            db.delete(ticket)

        db.delete(event)
        db.commit()

    except IntegrityError:
        handle_database_integrity_error(
            db,
            "This event has related records and cannot be deleted.",
        )

    return RedirectResponse(
        url="/admin/events/",
        status_code=303,
    )


# --------------------------------------------------
# Add ticket category
# --------------------------------------------------

@router.get(
    "/{event_id}/tickets/new",
    response_class=HTMLResponse,
)
def new_ticket_category_form(
    event_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    event = get_event_or_404(db, event_id)
    require_draft(event)

    return render_category_form(
        request,
        event=event,
    )


@router.post("/{event_id}/tickets/new")
def create_ticket_category(
    event_id: int,
    request: Request,
    name: str = Form(...),
    price: str = Form(...),
    quantity: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    verify_csrf_token(request, csrf_token)

    form_data = category_form_values(
        name, price, quantity
    )

    try:
        event = lock_event_or_404(db, event_id)
        require_draft(event)

        cleaned = validate_ticket_category(**form_data)

        venue = db.get(Venue, event.venue_id)

        check_ticket_capacity(
            db=db,
            event_id=event_id,
            venue_capacity=venue.capacity,
            new_quantity=cleaned["quantity"],
        )

        existing = db.scalar(
            select(TicketCategory).where(
                TicketCategory.event_id == event_id,
                TicketCategory.name == cleaned["name"],
            )
        )

        if existing is not None:
            raise EventValidationError(
                "A ticket category with this name already exists."
            )

        ticket = TicketCategory(
            event_id=event_id,
            **cleaned,
            sold_count=0,
        )

        db.add(ticket)
        db.commit()

        return redirect_to_event(event_id)

    except EventValidationError as exc:
        db.rollback()

        event = get_event_or_404(db, event_id)

        return render_category_form(
            request,
            event=event,
            error=str(exc),
            form_data=form_data,
            status_code=400,
        )

    except IntegrityError:
        handle_database_integrity_error(
            db,
            "This ticket category already exists.",
        )


# --------------------------------------------------
# Edit ticket category
# --------------------------------------------------

@router.get(
    "/{event_id}/tickets/{category_id}/edit",
    response_class=HTMLResponse,
)
def edit_ticket_category_form(
    event_id: int,
    category_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    event = get_event_or_404(db, event_id)
    require_draft(event)

    category = get_category_or_404(
        db, event_id, category_id
    )

    return render_category_form(
        request,
        event=event,
        category=category,
    )


@router.post(
    "/{event_id}/tickets/{category_id}/edit"
)
def update_ticket_category(
    event_id: int,
    category_id: int,
    request: Request,
    name: str = Form(...),
    price: str = Form(...),
    quantity: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    verify_csrf_token(request, csrf_token)

    form_data = category_form_values(
        name, price, quantity
    )

    try:
        event = lock_event_or_404(db, event_id)
        require_draft(event)

        ticket = get_category_or_404(
            db, event_id, category_id
        )

        cleaned = validate_ticket_category(**form_data)

        if cleaned["quantity"] < ticket.sold_count:
            raise EventValidationError(
                "Quantity cannot be lower than tickets already sold."
            )

        venue = db.get(Venue, event.venue_id)

        check_ticket_capacity(
            db=db,
            event_id=event_id,
            venue_capacity=venue.capacity,
            new_quantity=cleaned["quantity"],
            exclude_category_id=category_id,
        )

        duplicate = db.scalar(
            select(TicketCategory).where(
                TicketCategory.event_id == event_id,
                TicketCategory.name == cleaned["name"],
                TicketCategory.id != category_id,
            )
        )

        if duplicate is not None:
            raise EventValidationError(
                "A ticket category with this name already exists."
            )

        for field, value in cleaned.items():
            setattr(ticket, field, value)

        db.commit()

        return redirect_to_event(event_id)

    except EventValidationError as exc:
        db.rollback()

        event = get_event_or_404(db, event_id)
        ticket = get_category_or_404(
            db, event_id, category_id
        )

        return render_category_form(
            request,
            event=event,
            category=ticket,
            error=str(exc),
            form_data=form_data,
            status_code=400,
        )

    except IntegrityError:
        handle_database_integrity_error(
            db,
            "This ticket category name is already in use.",
        )


# --------------------------------------------------
# Delete ticket category
# --------------------------------------------------

@router.post(
    "/{event_id}/tickets/{category_id}/delete"
)
def delete_ticket_category(
    event_id: int,
    category_id: int,
    request: Request,
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    verify_csrf_token(request, csrf_token)

    event = lock_event_or_404(db, event_id)
    require_draft(event)

    ticket = get_category_or_404(
        db, event_id, category_id
    )

    if ticket.sold_count > 0:
        raise HTTPException(
            status_code=409,
            detail="Cannot delete a category with sold tickets.",
        )

    try:
        db.delete(ticket)
        db.commit()

    except IntegrityError:
        handle_database_integrity_error(
            db,
            "This category has related bookings or tickets.",
        )

    return redirect_to_event(event_id)
