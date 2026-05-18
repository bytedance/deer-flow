"""Tests for RSA encryption utilities."""

import base64

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.gateway.auth.rsa_utils import normalize_pem, rsa_encrypt


@pytest.fixture(scope="module")
def rsa_key_pair():
    """Generate a 2048-bit RSA key pair for testing."""
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    public_key = private_key.public_key()
    public_key_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    return private_key, public_key_pem


def test_rsa_encrypt_then_decrypt(rsa_key_pair):
    """Round-trip: encrypt then decrypt should return original plaintext."""
    private_key, public_key_pem = rsa_key_pair
    from cryptography.hazmat.primitives.asymmetric import padding

    plaintext = "hello123"
    encrypted = rsa_encrypt(plaintext, public_key_pem)
    assert isinstance(encrypted, str)

    decoded = base64.b64decode(encrypted)
    decrypted = private_key.decrypt(decoded, padding.PKCS1v15()).decode("utf-8")
    assert decrypted == plaintext


def test_normalize_pem_single_line(rsa_key_pair):
    """Normalize handles single-line (stripped) PEM format."""
    _, public_key_pem = rsa_key_pair
    single_line = (
        public_key_pem.replace("\n", "")
        .replace("-----BEGIN PUBLIC KEY-----", "")
        .replace("-----END PUBLIC KEY-----", "")
    )
    mangled = f"-----BEGIN PUBLIC KEY-----{single_line}-----END PUBLIC KEY-----"
    result = normalize_pem(mangled)
    assert "-----BEGIN PUBLIC KEY-----\n" in result
    assert "\n-----END PUBLIC KEY-----\n" in result


def test_normalize_pem_with_spaces(rsa_key_pair):
    """Normalize handles PEM with extra whitespace."""
    _, public_key_pem = rsa_key_pair
    with_spaces = public_key_pem.replace("\n", " \n ")
    result = normalize_pem(with_spaces)
    assert "-----BEGIN PUBLIC KEY-----\n" in result


def test_normalize_pem_multiline(rsa_key_pair):
    """Normalize preserves valid multi-line PEM."""
    _, public_key_pem = rsa_key_pair
    result = normalize_pem(public_key_pem)
    assert result == public_key_pem


def test_rsa_encrypt_with_different_plaintexts(rsa_key_pair):
    """Different plaintexts produce different ciphertexts."""
    _, public_key_pem = rsa_key_pair

    encrypted_a = rsa_encrypt("plaintext_a", public_key_pem)
    encrypted_b = rsa_encrypt("plaintext_b", public_key_pem)
    assert encrypted_a != encrypted_b


def test_rsa_encrypt_empty_plaintext(rsa_key_pair):
    """Empty plaintext raises ValueError."""
    _, public_key_pem = rsa_key_pair
    with pytest.raises(ValueError, match="Plaintext is empty"):
        rsa_encrypt("", public_key_pem)


def test_rsa_encrypt_empty_key():
    """Empty public key raises ValueError."""
    with pytest.raises(ValueError, match="RSA public key is empty"):
        rsa_encrypt("test", "")


def test_rsa_encrypt_invalid_key():
    """Invalid public key raises error."""
    with pytest.raises(Exception):
        rsa_encrypt("test", "not-a-valid-key")
