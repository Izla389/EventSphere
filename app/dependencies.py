from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.models.models import UserRole


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    user_id = request.session.get("user_id")

    if not isinstance(user_id, int) or isinstance(user_id, bool):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Please log in first",
        )

    user = db.get(User, user_id)

    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session is no longer valid",
        )

    return user


def require_role(*allowed_roles: UserRole):
    def check_role(
        current_user: User = Depends(get_current_user),
    ) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to access this page",
            )

        return current_user

    return check_role