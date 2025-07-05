import base64
from src.tools.google_image import google_image_tool


def test_google_image_basic():
    """Basic test for Google Image tool."""
    b64 = google_image_tool.invoke("Generate an image of a cat")
    png_bytes = base64.b64decode(b64)
    assert len(png_bytes) > 100_000          
