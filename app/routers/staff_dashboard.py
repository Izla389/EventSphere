
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_role
from app.models.models import (
    Event,
    EventStaffAssignment,
    EventStatus,
    Ticket,
    TicketStatus,
    User,
    UserRole,
)


router = APIRouter(
    prefix="/staff",
    tags=["Staff Dashboard"],
)

templates = Jinja2Templates(
    directory="app/templates"
)


@router.get("/dashboard", response_class=HTMLResponse)
def staff_dashboard(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_role(UserRole.STAFF)
    ),
):
    # Get only published events assigned to this staff member.
    events = db.scalars(
        select(Event)
        .join(
            EventStaffAssignment,
            EventStaffAssignment.event_id == Event.id,
        )
        .where(
            Event.status == EventStatus.PUBLISHED,
            EventStaffAssignment.staff_user_id == current_user.id,
        )
        .order_by(Event.start_time)
    ).all()

    event_statistics = []

    for event in events:
        # Total tickets issued for this event.
        total_tickets = db.scalar(
            select(func.count(Ticket.id))
            .where(Ticket.event_id == event.id)
        ) or 0

        # Tickets already checked in.
        checked_in = db.scalar(
            select(func.count(Ticket.id))
            .where(
                Ticket.event_id == event.id,
                Ticket.status == TicketStatus.USED,
            )
        ) or 0

        # Tickets still valid for check-in.
        remaining = db.scalar(
            select(func.count(Ticket.id))
            .where(
                Ticket.event_id == event.id,
                Ticket.status == TicketStatus.VALID,
            )
        ) or 0

        # Percentage of issued tickets checked in.
        progress = (
            round((checked_in / total_tickets) * 100, 1)
            if total_tickets > 0
            else 0
        )

        event_statistics.append(
            {
                "event": event,
                "total_tickets": total_tickets,
                "checked_in": checked_in,
                "remaining": remaining,
                "progress": progress,
            }
        )

    return templates.TemplateResponse(
        request=request,
        name="staff_dashboard.html",
        context={
            "current_user": current_user,
            "event_statistics": event_statistics,
        },
    )
