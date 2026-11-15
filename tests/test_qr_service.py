
import io

import pytest
from PIL import Image

from app.qr_service import generate_ticket_qr


def test_qr_code_generates_valid_png():
    data = generate_ticket_qr("TEST-TICKET-123")

    assert isinstance(data, bytes)
    assert data.startswith(
        bytes.fromhex("89504E470D0A1A0A")
    )

    image = Image.open(io.BytesIO(data))
    assert image.format == "PNG"
    assert image.width > 0
    assert image.height > 0


def test_qr_code_rejects_empty_token():
    with pytest.raises(
        ValueError,
        match="QR token cannot be empty",
    ):
        generate_ticket_qr("")
