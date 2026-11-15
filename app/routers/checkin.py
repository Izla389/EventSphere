
from fastapi import (
    APIRouter,
    Depends,
    Form,
    HTTPException,
    Request,
)
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.checkin_service import (
    CheckInValidationError,
    check_in_ticket,
)
from app.database import get_db
from app.dependencies import require_role
from app.models.models import (
    Event,
    EventStatus,
    User,
    UserRole,
)
from app.security import (
    create_csrf_token,
    verify_csrf_token,
)


router = APIRouter(
    prefix="/staff/checkin",
    tags=["Staff Check-In"],
)

templates = Jinja2Templates(
    directory="app/templates"
)


@router.get("/", response_class=HTMLResponse)
def checkin_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_role(UserRole.STAFF)
    ),
):
    events = db.scalars(
        select(Event)
        .where(Event.status == EventStatus.PUBLISHED)
        .order_by(Event.start_time)
    ).all()

    return templates.TemplateResponse(
        request=request,
        name="staff_checkin.html",
        context={
            "events": events,
            "csrf_token": create_csrf_token(request),
            "message": None,
            "error": None,
        },
    )


@router.post("/", response_class=HTMLResponse)
def submit_checkin(
    request: Request,
    event_id: int = Form(...),
    qr_token: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_role(UserRole.STAFF)
    ),
):
    verify_csrf_token(request, csrf_token)

    events = db.scalars(
        select(Event)
        .where(Event.status == EventStatus.PUBLISHED)
        .order_by(Event.start_time)
    ).all()

    message = None
    error = None

    try:
        ticket = check_in_ticket(
            db,
            qr_token=qr_token,
            event_id=event_id,
            staff_user_id=current_user.id,
        )

        db.commit()

        message = (
            f"Ticket #{ticket.id} checked in successfully!"
        )

    except CheckInValidationError as exc:
        if exc.save_scan_attempt:
            try:
                db.commit()
            except Exception:
                db.rollback()
                raise
        else:
            db.rollback()

        error = str(exc)

    return templates.TemplateResponse(
        request=request,
        name="staff_checkin.html",
        context={
            "events": events,
            "csrf_token": create_csrf_token(request),
            "message": message,
            "error": error,
        },
    )
