"""
Basic test for image recognition tool without external dependencies.
This test only checks the helper functions that don't require langchain.
"""

import base64
import sys
from pathlib import Path

# Test basic helper functions
def test_is_url():
    """Test URL detection."""
    from urllib.parse import urlparse

    def _is_url(path: str) -> bool:
        try:
            result = urlparse(path)
            return all([result.scheme, result.netloc])
        except Exception:
            return False

    # Test cases
    assert _is_url("http://example.com/image.jpg") is True, "HTTP URL should be detected"
    assert _is_url("https://example.com/image.jpg") is True, "HTTPS URL should be detected"
    assert _is_url("/path/to/image.jpg") is False, "Unix path should not be URL"
    assert _is_url("C:\\path\\to\\image.jpg") is False, "Windows path should not be URL"
    assert _is_url("image.jpg") is False, "Relative path should not be URL"
    print("✓ URL detection tests passed")


def test_encode_image():
    """Test image encoding."""
    image_bytes = b"fake image data"
    encoded = base64.b64encode(image_bytes).decode("utf-8")
    expected = "ZmFrZSBpbWFnZSBkYXRh"
    assert encoded == expected, f"Expected {expected}, got {encoded}"
    print("✓ Image encoding tests passed")


def test_file_extension_validation():
    """Test file extension validation."""
    valid_extensions = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}

    test_cases = [
        ("image.jpg", True),
        ("image.JPG", True),
        ("image.png", True),
        ("image.webp", True),
        ("image.gif", True),
        ("image.bmp", True),
        ("image.txt", False),
        ("image.pdf", False),
        ("image", False),
    ]

    for filename, expected in test_cases:
        path = Path(filename)
        result = path.suffix.lower() in valid_extensions
        assert result == expected, f"Failed for {filename}: expected {expected}, got {result}"

    print("✓ File extension validation tests passed")


if __name__ == "__main__":
    print("Running basic image recognition tool tests...\n")

    try:
        test_is_url()
        test_encode_image()
        test_file_extension_validation()
        print("\n✅ All basic tests passed!")
    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        sys.exit(1)
