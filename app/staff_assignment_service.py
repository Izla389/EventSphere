
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.models import (
    Event,
    EventStaffAssignment,
    User,
    UserRole,
)


class StaffAssignmentError(Exception):
    pass


def assign_staff_to_event(
    db: Session,
    event_id: int,
    staff_user_id: int,
    admin_user_id: int,
):
    # Validate administrator
    admin = db.get(User, admin_user_id)

    if (
        admin is None
        or not admin.is_active
        or admin.role != UserRole.ADMIN
    ):
        raise StaffAssignmentError(
            "Only an active administrator can assign staff."
        )

    # Validate event
    event = db.get(Event, event_id)

    if event is None:
        raise StaffAssignmentError(
            "Event not found."
        )

    # Validate staff member
    staff = db.get(User, staff_user_id)

    if (
        staff is None
        or not staff.is_active
        or staff.role != UserRole.STAFF
    ):
        raise StaffAssignmentError(
            "Only active staff members can be assigned."
        )

    # Prevent duplicate assignments
    existing = db.scalar(
        select(EventStaffAssignment).where(
            EventStaffAssignment.event_id == event_id,
            EventStaffAssignment.staff_user_id == staff_user_id,
        )
    )

    if existing is not None:
        raise StaffAssignmentError(
            "This staff member is already assigned to the event."
        )

    assignment = EventStaffAssignment(
        event_id=event_id,
        staff_user_id=staff_user_id,
        assigned_by=admin_user_id,
    )

    db.add(assignment)
    db.flush()

    return assignment


def remove_staff_from_event(
    db: Session,
    assignment_id: int,
    admin_user_id: int,
):
    admin = db.get(User, admin_user_id)

    if (
        admin is None
        or not admin.is_active
        or admin.role != UserRole.ADMIN
    ):
        raise StaffAssignmentError(
            "Only an active administrator can remove assignments."
        )

    assignment = db.get(
        EventStaffAssignment,
        assignment_id,
    )

    if assignment is None:
        raise StaffAssignmentError(
            "Staff assignment not found."
        )

    db.delete(assignment)
    db.flush()

    return True

