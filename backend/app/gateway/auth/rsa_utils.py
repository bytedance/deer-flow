"""RSA encryption utilities for ins-base-rpc login credential encryption."""

import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding


def normalize_pem(key: str) -> str:
    """Normalize a RSA public key PEM string.

    Handles multi-line, single-line, and whitespace-including formats
    by stripping headers/footers/newlines/spaces and re-wrapping to
    64-char lines.
    """
    body = (
        key.replace("-----BEGIN PUBLIC KEY-----", "")
        .replace("-----END PUBLIC KEY-----", "")
        .replace("\n", "")
        .replace("\r", "")
        .replace(" ", "")
    )
    chunks = [body[i:i + 64] for i in range(0, len(body), 64)]
    return "-----BEGIN PUBLIC KEY-----\n" + "\n".join(chunks) + "\n-----END PUBLIC KEY-----\n"


def rsa_encrypt(plaintext: str, public_key_pem: str) -> str:
    """Encrypt plaintext using RSA public key with PKCS1v15 padding.

    Args:
        plaintext: The text to encrypt.
        public_key_pem: RSA public key in PEM format (may be single-line,
                        multi-line, or contain excess whitespace).

    Returns:
        Base64-encoded encrypted string.

    Raises:
        ValueError: If the public key is empty or invalid.
    """
    if not public_key_pem:
        raise ValueError("RSA public key is empty")
    if not plaintext:
        raise ValueError("Plaintext is empty")

    normalized = normalize_pem(public_key_pem)
    public_key = serialization.load_pem_public_key(normalized.encode("utf-8"))
    encrypted = public_key.encrypt(plaintext.encode("utf-8"), padding.PKCS1v15())
    return base64.b64encode(encrypted).decode("utf-8")
