"""Small encrypted, atomically replaced runtime catalog for administrator settings."""

import json
import os
import tempfile
from pathlib import Path


class EncryptedCatalog:
    def __init__(self, path: Path):
        self.path = path
        self.key_path = path.with_name("key")

    def _cipher(self, *, create: bool = False):
        from cryptography.fernet import Fernet

        if not self.key_path.exists():
            if not create or self.path.exists():
                raise ValueError("Catalog encryption key is missing; restore it from backup")
            self.write_bytes(self.key_path, Fernet.generate_key())
        return Fernet(self.key_path.read_bytes())

    def read(self) -> list[dict]:
        if not self.path.exists():
            return []
        try:
            records = json.loads(self._cipher().decrypt(self.path.read_bytes()))
            if not isinstance(records, list) or any(not isinstance(item, dict) for item in records):
                raise ValueError("Invalid catalog")
            return records
        except Exception:
            # Invalid decrypted inputs and provider secrets must never reach logs.
            raise ValueError("Cannot read encrypted catalog; check the catalog and encryption key") from None

    def write(self, records: list[dict]) -> None:
        payload = json.dumps(records).encode("utf-8")
        cipher = self._cipher(create=True)
        self.write_bytes(self.path, cipher.encrypt(payload))

    @staticmethod
    def write_bytes(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
