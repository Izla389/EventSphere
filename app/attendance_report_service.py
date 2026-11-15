
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.models import (
    Booking,
    BookingStatus,
    Event,
    Ticket,
    TicketStatus,
    Venue,
)


def get_event_attendance_report(
    db: Session,
    event_id: int,
):
    """
    Generate an attendance report for one event.

    Returns None when the event does not exist.
    """

    event = db.get(Event, event_id)

    if event is None:
        return None

    venue = db.get(Venue, event.venue_id)

    # Count active tickets belonging to confirmed bookings.
    total_tickets = db.scalar(
        select(func.count(Ticket.id))
        .join(
            Booking,
            Ticket.booking_id == Booking.id,
        )
        .where(
            Ticket.event_id == event_id,
            Booking.event_id == event_id,
            Booking.status == BookingStatus.CONFIRMED,
            Ticket.status.in_(
                [
                    TicketStatus.VALID,
                    TicketStatus.USED,
                ]
            ),
        )
    ) or 0

    # Count checked-in tickets.
    checked_in = db.scalar(
        select(func.count(Ticket.id))
        .join(
            Booking,
            Ticket.booking_id == Booking.id,
        )
        .where(
            Ticket.event_id == event_id,
            Booking.event_id == event_id,
            Booking.status == BookingStatus.CONFIRMED,
            Ticket.status == TicketStatus.USED,
        )
    ) or 0

    # Attendees who have not checked in.
    remaining = total_tickets - checked_in

    # Attendance percentage.
    attendance_percentage = (
        round((checked_in / total_tickets) * 100, 2)
        if total_tickets > 0
        else 0.0
    )

    return {
        "event_id": event.id,
        "event_title": event.title,
        "event_status": event.status.value,
        "start_time": event.start_time,
        "venue_name": venue.name if venue else "Unknown",
        "total_tickets": total_tickets,
        "checked_in": checked_in,
        "remaining": remaining,
        "attendance_percentage": attendance_percentage,
    }


def get_all_event_attendance_reports(db: Session):
    """
    Generate attendance reports for all events.
    """

    events = db.scalars(
        select(Event).order_by(
            Event.start_time.desc()
        )
    ).all()

    reports = []

    for event in events:
        report = get_event_attendance_report(
            db,
            event.id,
        )

        if report is not None:
            reports.append(report)

    return reports
