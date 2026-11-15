
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import (
    AgentInbox,
    AgentMessage,
    AgentState,
    UserRole,
)
from app.dependencies import require_role


router = APIRouter(prefix="/admin/agents", tags=["Agents"])


@router.get("/", response_class=HTMLResponse)
def agent_dashboard(
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_role(UserRole.ADMIN)),
):
    messages = db.scalars(
        select(AgentMessage)
        .order_by(AgentMessage.created_at.desc())
        .limit(100)
    ).all()

    states = db.scalars(
        select(AgentState)
        .order_by(AgentState.agent_name)
    ).all()

    pending_count = len(
        db.scalars(
            select(AgentInbox).where(
                AgentInbox.processed.is_(False)
            )
        ).all()
    )

    from fastapi.templating import Jinja2Templates

    templates = Jinja2Templates(directory="app/templates")

    return templates.TemplateResponse(
        request=request,
        name="agent_dashboard.html",
        context={
            "user": user,
            "messages": messages,
            "states": states,
            "pending_count": pending_count,
        },
    )
