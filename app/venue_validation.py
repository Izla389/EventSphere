from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse


class VenueValidationError(ValueError):
    pass


def validate_venue(
    name: str,
    location: str,
    capacity: str,
    description: str,
    image_url: str,
    hourly_hire_rate: str,
    is_open_for_hire: bool,
) -> dict:
    name = name.strip()
    location = location.strip()
    description = description.strip()
    image_url = image_url.strip()

    if not 2 <= len(name) <= 200:
        raise VenueValidationError(
            "Venue name must contain 2 to 200 characters."
        )

    if not 2 <= len(location) <= 255:
        raise VenueValidationError(
            "Location must contain 2 to 255 characters."
        )

    if len(description) > 5000:
        raise VenueValidationError(
            "Description cannot exceed 5000 characters."
        )

    if image_url:
        parsed = urlparse(image_url)

        if (
            len(image_url) > 500
            or parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
        ):
            raise VenueValidationError(
                "Image URL must be a valid HTTPS URL (maximum 500 characters)."
            )

    try:
        capacity_value = int(capacity)
    except (ValueError, TypeError):
        raise VenueValidationError(
            "Capacity must be a whole number."
        )

    if not 1 <= capacity_value <= 1_000_000:
        raise VenueValidationError(
            "Capacity must be between 1 and 1,000,000."
        )

    try:
        rate = Decimal(hourly_hire_rate)
    except (InvalidOperation, TypeError):
        raise VenueValidationError(
            "Hourly hire rate must be a valid number."
        )

    if (
        not rate.is_finite()
        or rate < 0
        or rate > Decimal("9999999999.99")
        or rate.as_tuple().exponent < -2
    ):
        raise VenueValidationError(
            "Hourly hire rate must be non-negative, "
            "have at most two decimal places, and fit the database field."
        )

    return {
        "name": name,
        "location": location,
        "capacity": capacity_value,
        "description": description or None,
        "image_url": image_url or None,
        "hourly_hire_rate": rate,
        "is_open_for_hire": is_open_for_hire,
    }