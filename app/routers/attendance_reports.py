
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.attendance_report_service import (
    get_all_event_attendance_reports,
)
from app.database import get_db
from app.dependencies import require_role
from app.models.models import User, UserRole


router = APIRouter(
    prefix="/admin",
    tags=["Attendance Reports"],
)

templates = Jinja2Templates(
    directory="app/templates"
)


@router.get(
    "/attendance-reports/",
    response_class=HTMLResponse,
)
def attendance_reports_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_role(UserRole.ADMIN)
    ),
):
    """
    Display attendance reports for all events.

    Only authenticated, active admins can access
    this page.
    """

    reports = get_all_event_attendance_reports(db)

    return templates.TemplateResponse(
        request=request,
        name="attendance_reports.html",
        context={
            "current_user": current_user,
            "reports": reports,
        },
    )
