import getpass
import sys

from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import User
from app.models.models import UserRole
from app.security import hash_password

def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ("admin", "staff"):
        print("Usage: python -m scripts.create_user admin")
        print("   or: python -m scripts.create_user staff")
        return

    role = UserRole(sys.argv[1])

    print(f"\nCreate EventSphere {role.value} account")

    full_name = input("Full name: ").strip()
    email_input = input("Email: ").strip().lower()
    password = getpass.getpass("Password (minimum 12 characters): ")
    confirm = getpass.getpass("Confirm password: ")

    if not 2 <= len(full_name) <= 150:
        print("Error: Name must contain 2 to 150 characters.")
        return

    try:
        email = str(
            TypeAdapter(EmailStr).validate_python(email_input)
        )
    except ValidationError:
        print("Error: Invalid email address.")
        return

    if not 12 <= len(password) <= 128:
        print("Error: Password must contain 12 to 128 characters.")
        return

    if password != confirm:
        print("Error: Passwords do not match.")
        return

    with SessionLocal() as db:
        existing = db.scalar(
            select(User).where(func.lower(User.email) == email)
        )

        if existing:
            print("Error: An account with this email already exists.")
            return

        user = User(
            full_name=full_name,
            email=email,
            password_hash=hash_password(password),
            role=role,
            is_active=True,
        )

        db.add(user)
        db.commit()

    print(f"\nSuccess! {role.value} account created.")
    print("You can now log in at http://127.0.0.1:8000/login")

if __name__ == "__main__":
    main()