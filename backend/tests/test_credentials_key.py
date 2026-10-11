"""At-rest credentials key ``DEER_FLOW_CREDENTIALS_KEY`` and the cipher built from it.

The key is env-only: one or more comma-separated urlsafe-base64 Fernet keys,
the first encrypting and every one decrypting, so an operator rotates by
prepending a new key. Without it a single instance generates
``{base_dir}/.credentials_key`` once. It is never derived from
``AUTH_JWT_SECRET``.
"""

from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path

import pytest
from cryptography.fernet import Fernet, InvalidToken

from deerflow.config import credentials_key as ck
from deerflow.config.credentials_key import (
    CIPHERTEXT_PREFIX,
    CREDENTIALS_KEY_ENV_VAR,
    CREDENTIALS_KEY_FILENAME,
    GENERATE_KEY_COMMAND,
    CredentialsCipher,
    CredentialsDecryptError,
    CredentialsKeyError,
    get_credentials_cipher,
    load_credentials_cipher,
    parse_credentials_keys,
    reset_credentials_cipher,
)
from deerflow.persistence.channel_connections import ChannelCredentialCipher

KEY_OLD = Fernet.generate_key().decode("ascii")
KEY_NEW = Fernet.generate_key().decode("ascii")


@pytest.fixture(autouse=True)
def _isolated_key_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv(CREDENTIALS_KEY_ENV_VAR, raising=False)
    reset_credentials_cipher()
    yield
    reset_credentials_cipher()


def _std_base64_key() -> str:
    """A 32-byte key spelled with the standard alphabet (``+``/``/``), as Helm's randBytes emits it."""
    raw = bytes([0xFB, 0xFF] * 16)
    value = base64.b64encode(raw).decode("ascii")
    assert "+" in value or "/" in value
    return value


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def test_parse_accepts_a_single_key() -> None:
    assert parse_credentials_keys(KEY_NEW) == [KEY_NEW]


def test_parse_keeps_rotation_order_and_ignores_blank_entries() -> None:
    assert parse_credentials_keys(f" {KEY_NEW} , {KEY_OLD} ,") == [KEY_NEW, KEY_OLD]


@pytest.mark.parametrize(
    "raw",
    [
        "",
        " , ",
        "not-a-fernet-key",
        KEY_NEW[:-1],
        KEY_NEW + "A",
        _std_base64_key(),
        "é" * 44,
        f"{KEY_NEW},short-second-key",
    ],
    ids=["empty", "only-separators", "garbage", "truncated", "too-long", "standard-alphabet", "non-ascii", "second-entry-bad"],
)
def test_parse_rejects_malformed_keys_without_echoing_them(raw: str) -> None:
    with pytest.raises(CredentialsKeyError) as exc_info:
        parse_credentials_keys(raw)

    message = str(exc_info.value)
    assert CREDENTIALS_KEY_ENV_VAR in message
    assert GENERATE_KEY_COMMAND in message, "the refusal must say how to generate a valid key"
    for entry in filter(None, (part.strip() for part in raw.split(","))):
        assert entry not in message, "key material must never reach logs or refusal text"
    assert exc_info.value.__cause__ is None


# ---------------------------------------------------------------------------
# Cipher
# ---------------------------------------------------------------------------


def test_cipher_writes_a_versioned_prefix_and_round_trips() -> None:
    cipher = CredentialsCipher.from_keys([KEY_NEW])

    token = cipher.encrypt_text("xoxb-secret")

    assert token.startswith(CIPHERTEXT_PREFIX)
    assert CIPHERTEXT_PREFIX == "fernet:v2:"
    assert "xoxb-secret" not in token
    assert cipher.decrypt_text(token) == "xoxb-secret"


def test_the_first_key_encrypts_and_every_key_decrypts() -> None:
    old_token = CredentialsCipher.from_keys([KEY_OLD]).encrypt_text("written-before-rotation")
    rotated = CredentialsCipher.from_keys([KEY_NEW, KEY_OLD])

    assert rotated.decrypt_text(old_token) == "written-before-rotation"

    new_token = rotated.encrypt_text("written-after-rotation")
    assert CredentialsCipher.from_keys([KEY_NEW]).decrypt_text(new_token) == "written-after-rotation"
    with pytest.raises(CredentialsDecryptError):
        CredentialsCipher.from_keys([KEY_OLD]).decrypt_text(new_token)


def test_rotate_re_encrypts_under_the_primary_key() -> None:
    old_token = CredentialsCipher.from_keys([KEY_OLD]).encrypt_text("long-lived-token")
    rotated = CredentialsCipher.from_keys([KEY_NEW, KEY_OLD])

    re_encrypted = rotated.rotate_text(old_token)

    assert re_encrypted.startswith(CIPHERTEXT_PREFIX)
    assert CredentialsCipher.from_keys([KEY_NEW]).decrypt_text(re_encrypted) == "long-lived-token"


def test_an_undecryptable_value_raises_an_invalid_token_subclass() -> None:
    token = CredentialsCipher.from_keys([KEY_OLD]).encrypt_text("secret")
    cipher = CredentialsCipher.from_keys([KEY_NEW])

    with pytest.raises(CredentialsDecryptError) as exc_info:
        cipher.decrypt_text(token)
    assert isinstance(exc_info.value, InvalidToken), "existing `except InvalidToken` call sites keep working"

    for garbage in ("fernet:v2:not-a-token", "fernet:v2:é", "plain text"):
        with pytest.raises(CredentialsDecryptError):
            cipher.decrypt_text(garbage)


def test_legacy_v1_values_written_by_the_passphrase_cipher_stay_readable() -> None:
    """Exactly what ``ChannelCredentialCipher.from_key`` wrote before the v2 format."""
    derived = Fernet(base64.urlsafe_b64encode(hashlib.sha256(b"legacy-passphrase").digest()))
    legacy_value = "fernet:v1:" + derived.encrypt(b"xoxb-legacy").decode("ascii")

    cipher = ChannelCredentialCipher.from_key("legacy-passphrase")

    assert cipher.decrypt_text(legacy_value) == "xoxb-legacy"
    assert cipher.decrypt_text(legacy_value.removeprefix("fernet:v1:")) == "xoxb-legacy", "the old reader accepted a bare token"
    assert cipher.encrypt_text("new-value").startswith(CIPHERTEXT_PREFIX)
    assert isinstance(cipher, CredentialsCipher)


def test_v1_values_under_a_raw_key_are_readable_by_the_deployment_cipher() -> None:
    """``ChannelCredentialCipher(Fernet(key))`` wrote ``fernet:v1:`` under a raw key; the same key in the env reads it."""
    legacy_value = "fernet:v1:" + Fernet(KEY_OLD).encrypt(b"value").decode("ascii")

    assert ChannelCredentialCipher(Fernet(KEY_OLD)).decrypt_text(legacy_value) == "value"
    assert CredentialsCipher.from_keys([KEY_NEW, KEY_OLD]).decrypt_text(legacy_value) == "value"


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def test_the_environment_key_list_wins_and_no_file_is_written(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(CREDENTIALS_KEY_ENV_VAR, f"{KEY_NEW},{KEY_OLD}")
    old_token = CredentialsCipher.from_keys([KEY_OLD]).encrypt_text("old")

    cipher = load_credentials_cipher(base_dir=tmp_path)

    assert cipher.decrypt_text(old_token) == "old"
    assert CredentialsCipher.from_keys([KEY_NEW]).decrypt_text(cipher.encrypt_text("new")) == "new"
    assert not (tmp_path / CREDENTIALS_KEY_FILENAME).exists()


def test_a_single_instance_generates_the_key_file_once(tmp_path: Path) -> None:
    first = load_credentials_cipher(base_dir=tmp_path)
    key_file = tmp_path / CREDENTIALS_KEY_FILENAME

    assert key_file.exists()
    persisted = key_file.read_text(encoding="utf-8").strip()
    assert parse_credentials_keys(persisted) == [persisted]
    if os.name == "posix":
        assert key_file.stat().st_mode & 0o777 == 0o600

    token = first.encrypt_text("survives a restart")
    assert load_credentials_cipher(base_dir=tmp_path).decrypt_text(token) == "survives a restart"
    assert key_file.read_text(encoding="utf-8").strip() == persisted


def test_a_blank_environment_value_means_unset(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Compose renders ``${DEER_FLOW_CREDENTIALS_KEY:-}`` as an empty string."""
    monkeypatch.setenv(CREDENTIALS_KEY_ENV_VAR, "  ")

    load_credentials_cipher(base_dir=tmp_path)

    assert (tmp_path / CREDENTIALS_KEY_FILENAME).exists()


def test_a_malformed_environment_key_is_refused_before_touching_disk(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(CREDENTIALS_KEY_ENV_VAR, "definitely-not-a-key")

    with pytest.raises(CredentialsKeyError):
        load_credentials_cipher(base_dir=tmp_path)

    assert not (tmp_path / CREDENTIALS_KEY_FILENAME).exists()


def test_a_corrupt_key_file_is_refused_and_left_alone(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The file may be the only copy of the key that encrypted stored credentials."""
    monkeypatch.setattr(ck, "_KEY_FILE_SETTLE_SECONDS", 0.05)
    key_file = tmp_path / CREDENTIALS_KEY_FILENAME
    key_file.write_text("corrupted-key-material", encoding="utf-8")

    with pytest.raises(CredentialsKeyError) as exc_info:
        load_credentials_cipher(base_dir=tmp_path)

    assert str(key_file) in str(exc_info.value)
    assert "corrupted-key-material" not in str(exc_info.value)
    assert key_file.read_text(encoding="utf-8") == "corrupted-key-material"


def test_the_key_is_never_derived_from_the_jwt_secret(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AUTH_JWT_SECRET", KEY_OLD)
    jwt_derived_token = CredentialsCipher.from_keys([KEY_OLD]).encrypt_text("secret")

    cipher = load_credentials_cipher(base_dir=tmp_path)

    with pytest.raises(CredentialsDecryptError):
        cipher.decrypt_text(jwt_derived_token)
    assert (tmp_path / CREDENTIALS_KEY_FILENAME).read_text(encoding="utf-8").strip() != KEY_OLD


def test_the_process_cipher_is_loaded_once_until_reset(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from deerflow.config.paths import Paths

    monkeypatch.setattr("deerflow.config.paths.get_paths", lambda: Paths(base_dir=tmp_path))
    monkeypatch.setenv(CREDENTIALS_KEY_ENV_VAR, KEY_OLD)

    first = get_credentials_cipher()
    monkeypatch.setenv(CREDENTIALS_KEY_ENV_VAR, KEY_NEW)
    assert get_credentials_cipher() is first

    reset_credentials_cipher()
    reloaded = get_credentials_cipher()
    assert reloaded is not first
    assert CredentialsCipher.from_keys([KEY_NEW]).decrypt_text(reloaded.encrypt_text("x")) == "x"
