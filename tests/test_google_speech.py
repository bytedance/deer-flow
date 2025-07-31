import base64
from src.tools.google_speech import google_speech_tool


def test_google_speech_basic():
    """Basic test for Google Speech tool."""
    b64 = google_speech_tool.invoke("Hello, this is a test message for speech generation.")
    audio_bytes = base64.b64decode(b64)
    assert len(audio_bytes) > 1_000 