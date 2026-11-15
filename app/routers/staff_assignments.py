
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_role
from app.models.models import (
    Event,
    EventStaffAssignment,
    User,
    UserRole,
)
from app.security import create_csrf_token, verify_csrf_token
from app.staff_assignment_service import (
    StaffAssignmentError,
    assign_staff_to_event,
    remove_staff_from_event,
)


router = APIRouter(
    prefix="/admin/staff-assignments",
    tags=["Staff Assignments"],
)

templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
def staff_assignments_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    events = db.scalars(
        select(Event).order_by(Event.start_time)
    ).all()

    staff_members = db.scalars(
        select(User)
        .where(
            User.role == UserRole.STAFF,
            User.is_active.is_(True),
        )
        .order_by(User.full_name)
    ).all()

    assignments = db.execute(
        select(
            EventStaffAssignment,
            Event.title,
            User.full_name,
        )
        .join(
            Event,
            EventStaffAssignment.event_id == Event.id,
        )
        .join(
            User,
            EventStaffAssignment.staff_user_id == User.id,
        )
        .order_by(Event.title, User.full_name)
    ).all()

    return templates.TemplateResponse(
        request=request,
        name="staff_assignments.html",
        context={
            "current_user": current_user,
            "events": events,
            "staff_members": staff_members,
            "assignments": assignments,
            "csrf_token": create_csrf_token(request),
        },
    )


@router.post("/assign")
def assign_staff(
    request: Request,
    event_id: int = Form(...),
    staff_user_id: int = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    verify_csrf_token(request, csrf_token)

    try:
        assign_staff_to_event(
            db=db,
            event_id=event_id,
            staff_user_id=staff_user_id,
            admin_user_id=current_user.id,
        )
        db.commit()
    except StaffAssignmentError as exc:
        db.rollback()
        return RedirectResponse(
            url=f"/admin/staff-assignments/?error={str(exc).replace(' ', '+')}",
            status_code=303,
        )

    return RedirectResponse(
        url="/admin/staff-assignments/?success=assigned",
        status_code=303,
    )


@router.post("/remove")
def remove_staff(
    request: Request,
    assignment_id: int = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    verify_csrf_token(request, csrf_token)

    try:
        remove_staff_from_event(
            db=db,
            assignment_id=assignment_id,
            admin_user_id=current_user.id,
        )
        db.commit()
    except StaffAssignmentError as exc:
        db.rollback()
        return RedirectResponse(
            url=f"/admin/staff-assignments/?error={str(exc).replace(' ', '+')}",
            status_code=303,
        )

    return RedirectResponse(
        url="/admin/staff-assignments/?success=removed",
        status_code=303,
    )
