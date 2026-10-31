"""At-rest encryption key for stored credentials (``DEER_FLOW_CREDENTIALS_KEY``).

The key is environment-only: one or more comma-separated Fernet keys
(urlsafe base64 of 32 random bytes). The first key encrypts and every key
decrypts, so rotation is "prepend a new key, re-encrypt with
:meth:`CredentialsCipher.rotate_text`, then drop the old key". It is never
derived from ``AUTH_JWT_SECRET`` or any other secret.

Without the variable a single instance generates ``{base_dir}/.credentials_key``
once (exclusive create, mode ``0600``), so uvicorn workers sharing the runtime
home converge on one key. Instances that do not share a runtime home cannot
rely on that file; the Gateway refuses a declared multi-instance deployment
whose enabled features store credentials without the variable
(``app.gateway.deps._enforce_credentials_key``).

Losing the key makes every value encrypted with it unreadable; consumers treat
such values as missing rather than failing.

Ciphertext format: ``fernet:v2:<Fernet token>``. ``fernet:v1:`` (and bare
tokens) were written by the earlier ``ChannelCredentialCipher``; they are still
decrypted with the configured keys.
"""

from __future__ import annotations

import logging
import os
import re
import threading
from collections.abc import Sequence
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from deerflow.config.secret_file import InvalidSecretFileError, read_or_create_secret_file

logger = logging.getLogger(__name__)

CREDENTIALS_KEY_ENV_VAR = "DEER_FLOW_CREDENTIALS_KEY"
CREDENTIALS_KEY_FILENAME = ".credentials_key"
CIPHERTEXT_PREFIX = "fernet:v2:"
LEGACY_CIPHERTEXT_PREFIX = "fernet:v1:"
GENERATE_KEY_COMMAND = 'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'

# urlsafe base64 of exactly 32 bytes: 43 alphabet characters plus one "=" pad.
_FERNET_KEY_PATTERN = re.compile(r"[A-Za-z0-9_-]{43}=")
_KEY_FILE_SETTLE_SECONDS = 1.0


class CredentialsKeyError(ValueError):
    """The configured key material is unusable. The message never contains key material."""


class CredentialsDecryptError(InvalidToken):
    """A stored value cannot be decrypted with any configured key (wrong or lost key, or corrupt data)."""


def parse_credentials_keys(raw: str, *, source: str = CREDENTIALS_KEY_ENV_VAR) -> list[str]:
    """Split and validate a comma-separated key list; blank entries are ignored.

    ``source`` names where the value came from in error messages.
    """
    keys = [part.strip() for part in raw.split(",") if part.strip()]
    if not keys:
        raise CredentialsKeyError(f"{source} holds no key. Generate one with: {GENERATE_KEY_COMMAND}")
    for index, key in enumerate(keys, start=1):
        if not _is_fernet_key(key):
            position = f"entry {index} of {len(keys)}" if len(keys) > 1 else "the value"
            raise CredentialsKeyError(f"{source}: {position} is not a Fernet key (urlsafe base64 of 32 bytes, 44 characters). Generate one with: {GENERATE_KEY_COMMAND}")
    return keys


def _is_fernet_key(key: str) -> bool:
    if not _FERNET_KEY_PATTERN.fullmatch(key):
        return False
    try:
        Fernet(key)
    except (TypeError, ValueError):
        return False
    return True


class CredentialsCipher:
    """Text encryption under the deployment credentials key(s).

    Built on :class:`cryptography.fernet.MultiFernet`: the first key encrypts,
    every key decrypts. Values carry the ``fernet:v2:`` prefix.
    """

    def __init__(self, fernets: Sequence[Fernet]) -> None:
        if not fernets:
            raise CredentialsKeyError("at least one credentials key is required")
        self._multi = MultiFernet(list(fernets))

    @classmethod
    def from_keys(cls, keys: Sequence[str | bytes]) -> CredentialsCipher:
        return cls([Fernet(key) for key in keys])

    def encrypt_text(self, value: str) -> str:
        return CIPHERTEXT_PREFIX + self._multi.encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt_text(self, value: str) -> str:
        """Decrypt a ``fernet:v2:`` value, or a legacy ``fernet:v1:`` / bare token.

        Raises :class:`CredentialsDecryptError` (an ``InvalidToken``) when no
        configured key can decrypt it.
        """
        token = value.removeprefix(CIPHERTEXT_PREFIX) if value.startswith(CIPHERTEXT_PREFIX) else value.removeprefix(LEGACY_CIPHERTEXT_PREFIX)
        try:
            return self._multi.decrypt(token.encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeError):
            raise CredentialsDecryptError("stored value cannot be decrypted with the configured credentials key(s)") from None

    def rotate_text(self, value: str) -> str:
        """Re-encrypt ``value`` under the primary (first) key, for re-encryption after rotation."""
        return self.encrypt_text(self.decrypt_text(value))


def load_credentials_cipher(*, base_dir: Path | None = None) -> CredentialsCipher:
    """Build the deployment cipher from ``DEER_FLOW_CREDENTIALS_KEY``, else the generated key file.

    Performs file I/O when the variable is unset; async callers must run it in
    a worker thread. Raises :class:`CredentialsKeyError` for malformed key
    material in either source.
    """
    raw = os.environ.get(CREDENTIALS_KEY_ENV_VAR, "")
    if raw.strip():
        return CredentialsCipher.from_keys(parse_credentials_keys(raw))

    if base_dir is None:
        from deerflow.config.paths import get_paths

        base_dir = get_paths().base_dir
    key_file = Path(base_dir) / CREDENTIALS_KEY_FILENAME
    try:
        value = read_or_create_secret_file(
            key_file,
            lambda: Fernet.generate_key().decode("ascii"),
            validate=lambda candidate: parse_credentials_keys(candidate, source=str(key_file)),
            settle_seconds=_KEY_FILE_SETTLE_SECONDS,
        )
    except InvalidSecretFileError:
        raise CredentialsKeyError(f"{key_file} does not hold a valid credentials key. Restore it from a backup (stored credentials are unreadable without it), or set {CREDENTIALS_KEY_ENV_VAR}.") from None
    logger.info("%s is not set; using the credentials key in %s. Back this file up: losing it makes stored credentials unreadable.", CREDENTIALS_KEY_ENV_VAR, key_file)
    return CredentialsCipher.from_keys(parse_credentials_keys(value, source=str(key_file)))


_cipher: CredentialsCipher | None = None
_cipher_lock = threading.Lock()


def get_credentials_cipher() -> CredentialsCipher:
    """Return the process-wide cipher, loading it on first use (may perform file I/O)."""
    global _cipher
    with _cipher_lock:
        if _cipher is None:
            _cipher = load_credentials_cipher()
        return _cipher


def reset_credentials_cipher() -> None:
    """Forget the process-wide cipher so the next call reloads it (tests, key rotation on restart)."""
    global _cipher
    with _cipher_lock:
        _cipher = None
