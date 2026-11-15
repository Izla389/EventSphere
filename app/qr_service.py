
import io

import qrcode


def generate_ticket_qr(qr_token: str) -> bytes:
    """
    Generate a PNG QR code for a ticket.

    The QR code contains the ticket's unique
    random token, not personal information.
    """

    if not qr_token:
        raise ValueError("QR token cannot be empty.")

    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )

    qr.add_data(qr_token)
    qr.make(fit=True)

    image = qr.make_image(
        fill_color="black",
        back_color="white",
    )

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")

    return buffer.getvalue()
