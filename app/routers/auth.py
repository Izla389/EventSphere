from fastapi import (
    APIRouter,
    Depends,
    Form,
    HTTPException,
    Request,
    status,
)
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user, require_role
from app.models import User
from app.models.models import UserRole
from app.security import (
    create_csrf_token,
    end_user_session,
    hash_password,
    start_user_session,
    verify_csrf_token,
    verify_password,
)


router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
email_validator = TypeAdapter(EmailStr)


def show_form(
    request: Request,
    template_name: str,
    error: str | None = None,
    status_code: int = 200,
):
    return templates.TemplateResponse(
        request=request,
        name=template_name,
        context={
            "csrf_token": create_csrf_token(request),
            "error": error,
        },
        status_code=status_code,
    )


@router.get("/register", response_class=HTMLResponse)
def registration_page(request: Request):
    return show_form(request, "register.html")


@router.post("/register")
def register(
    request: Request,
    full_name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    verify_csrf_token(request, csrf_token)

    full_name = full_name.strip()
    email = email.strip().lower()

    if len(full_name) < 2 or len(full_name) > 150:
        return show_form(
            request, "register.html",
            "Name must contain 2 to 150 characters.", 400
        )

    try:
        email = str(email_validator.validate_python(email))
    except ValidationError:
        return show_form(
            request, "register.html",
            "Enter a valid email address.", 400
        )

    if len(password) < 12 or len(password) > 128:
        return show_form(
            request, "register.html",
            "Password must contain 12 to 128 characters.", 400
        )

    if password != confirm_password:
        return show_form(
            request, "register.html",
            "Passwords do not match.", 400
        )

    existing_user = db.scalar(
        select(User).where(func.lower(User.email) == email)
    )

    if existing_user:
        return show_form(
            request, "register.html",
            "An account with this email already exists.", 400
        )

    # Public registration always creates an attendee.
    # Never accept an admin/staff role from this form.
    user = User(
        full_name=full_name,
        email=email,
        password_hash=hash_password(password),
        role=UserRole.ATTENDEE,
        is_active=True,
    )

    db.add(user)

    try:
        db.commit()
        db.refresh(user)
    except IntegrityError:
        db.rollback()
        return show_form(
            request, "register.html",
            "An account with this email already exists.", 400
        )

    start_user_session(request, user.id)

    return RedirectResponse(
        url="/dashboard",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return show_form(request, "login.html")


@router.post("/login")
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    verify_csrf_token(request, csrf_token)

    email = email.strip().lower()

    user = db.scalar(
        select(User).where(func.lower(User.email) == email)
    )

    if (
        user is None
        or not user.is_active
        or not verify_password(password, user.password_hash)
    ):
        return show_form(
            request, "login.html",
            "Invalid email or password.", 401
        )

    start_user_session(request, user.id)

    return RedirectResponse(
        url="/dashboard",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/logout")
def logout(
    request: Request,
    csrf_token: str = Form(...),
):
    verify_csrf_token(request, csrf_token)
    end_user_session(request)

    return RedirectResponse(
        url="/login",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "user": current_user,
            "csrf_token": create_csrf_token(request),
        },
    )


@router.get("/admin", response_class=HTMLResponse)
def admin_dashboard(
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    return HTMLResponse(
        "<h1>EventSphere Admin Area</h1>"
        "<p>Admin access confirmed.</p>"
        '<a href="/dashboard">Back to dashboard</a>'
    )


@router.get("/staff", response_class=HTMLResponse)
def staff_dashboard(
    current_user: User = Depends(require_role(UserRole.STAFF)),
):
    return HTMLResponse(
        "<h1>EventSphere Gate Staff Area</h1>"
        "<p>Staff access confirmed.</p>"
        '<a href="/dashboard">Back to dashboard</a>'
    )


@router.get("/attendee", response_class=HTMLResponse)
def attendee_dashboard(
    current_user: User = Depends(require_role(UserRole.ATTENDEE)),
):
    return HTMLResponse(
        "<h1>EventSphere Attendee Area</h1>"
        "<p>Attendee access confirmed.</p>"
        '<a href="/dashboard">Back to dashboard</a>'
    )