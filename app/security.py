import secrets

from fastapi import HTTPException, Request, status
from pwdlib import PasswordHash


password_hasher = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return password_hasher.verify(password, password_hash)
    except (ValueError, TypeError):
        return False


def create_csrf_token(request: Request) -> str:
    token = request.session.get("csrf_token")

    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = token

    return token


def verify_csrf_token(request: Request, submitted_token: str) -> None:
    expected_token = request.session.get("csrf_token")

    if (
        not expected_token
        or not submitted_token
        or not secrets.compare_digest(expected_token, submitted_token)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing CSRF token",
        )


def start_user_session(request: Request, user_id: int) -> None:
    # Discard any existing session information and CSRF token.
    request.session.clear()
    request.session["user_id"] = user_id
    request.session["csrf_token"] = secrets.token_urlsafe(32)


def end_user_session(request: Request) -> None:
    request.session.clear()