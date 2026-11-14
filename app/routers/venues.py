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
from app.models import Venue
from app.models.models import UserRole
from app.security import create_csrf_token, verify_csrf_token
from app.venue_validation import (
    VenueValidationError,
    validate_venue,
)


router = APIRouter(
    prefix="/admin/venues",
    tags=["Venue Management"],
    dependencies=[Depends(require_role(UserRole.ADMIN))],
)

templates = Jinja2Templates(directory="app/templates")


def get_venue_or_404(db: Session, venue_id: int) -> Venue:
    venue = db.get(Venue, venue_id)

    if venue is None:
        raise HTTPException(
            status_code=404,
            detail="Venue not found",
        )

    return venue


def render_form(
    request: Request,
    *,
    venue=None,
    error=None,
    form_data=None,
    status_code=200,
):
    return templates.TemplateResponse(
        request=request,
        name="venue_form.html",
        context={
            "venue": venue,
            "error": error,
            "form_data": form_data,
            "csrf_token": create_csrf_token(request),
        },
        status_code=status_code,
    )


@router.get("/", response_class=HTMLResponse)
def list_venues(
    request: Request,
    db: Session = Depends(get_db),
):
    venues = db.scalars(
        select(Venue).order_by(Venue.id.desc())
    ).all()

    return templates.TemplateResponse(
        request=request,
        name="venues_list.html",
        context={
            "venues": venues,
            "csrf_token": create_csrf_token(request),
        },
    )


@router.get("/new", response_class=HTMLResponse)
def new_venue_form(request: Request):
    return render_form(request)


@router.post("/new")
def create_venue(
    request: Request,
    name: str = Form(...),
    location: str = Form(...),
    capacity: str = Form(...),
    description: str = Form(""),
    image_url: str = Form(""),
    hourly_hire_rate: str = Form(...),
    is_open_for_hire: bool = Form(False),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    verify_csrf_token(request, csrf_token)

    form_data = {
        "name": name,
        "location": location,
        "capacity": capacity,
        "description": description,
        "image_url": image_url,
        "hourly_hire_rate": hourly_hire_rate,
        "is_open_for_hire": is_open_for_hire,
    }

    try:
        cleaned = validate_venue(**form_data)
    except VenueValidationError as exc:
        return render_form(
            request,
            error=str(exc),
            form_data=form_data,
            status_code=400,
        )

    venue = Venue(**cleaned)
    db.add(venue)
    db.commit()
    db.refresh(venue)

    return RedirectResponse(
        url=f"/admin/venues/{venue.id}",
        status_code=303,
    )


@router.get("/{venue_id}", response_class=HTMLResponse)
def view_venue(
    venue_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    venue = get_venue_or_404(db, venue_id)

    return templates.TemplateResponse(
        request=request,
        name="venue_detail.html",
        context={
            "venue": venue,
            "csrf_token": create_csrf_token(request),
        },
    )


@router.get("/{venue_id}/edit", response_class=HTMLResponse)
def edit_venue_form(
    venue_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    venue = get_venue_or_404(db, venue_id)
    return render_form(request, venue=venue)


@router.post("/{venue_id}/edit")
def update_venue(
    venue_id: int,
    request: Request,
    name: str = Form(...),
    location: str = Form(...),
    capacity: str = Form(...),
    description: str = Form(""),
    image_url: str = Form(""),
    hourly_hire_rate: str = Form(...),
    is_open_for_hire: bool = Form(False),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    verify_csrf_token(request, csrf_token)

    venue = get_venue_or_404(db, venue_id)

    form_data = {
        "name": name,
        "location": location,
        "capacity": capacity,
        "description": description,
        "image_url": image_url,
        "hourly_hire_rate": hourly_hire_rate,
        "is_open_for_hire": is_open_for_hire,
    }

    try:
        cleaned = validate_venue(**form_data)
    except VenueValidationError as exc:
        return render_form(
            request,
            venue=venue,
            error=str(exc),
            form_data=form_data,
            status_code=400,
        )

    for field, value in cleaned.items():
        setattr(venue, field, value)

    db.commit()

    return RedirectResponse(
        url=f"/admin/venues/{venue.id}",
        status_code=303,
    )


@router.post("/{venue_id}/delete")
def delete_venue(
    venue_id: int,
    request: Request,
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    verify_csrf_token(request, csrf_token)

    venue = get_venue_or_404(db, venue_id)

    try:
        db.delete(venue)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=(
                "This venue is referenced by events or hire requests "
                "and cannot be deleted."
            ),
        )

    return RedirectResponse(
        url="/admin/venues/",
        status_code=303,
    )