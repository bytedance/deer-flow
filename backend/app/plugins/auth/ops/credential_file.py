"""Write initial admin credentials to a restricted file instead of logs."""

from __future__ import annotations

import os
from pathlib import Path

from deerflow.config.paths import get_paths

_CREDENTIAL_FILENAME = "admin_initial_credentials.txt"


def write_initial_credentials(email: str, password: str, *, label: str = "initial") -> Path:
    target = get_paths().base_dir / _CREDENTIAL_FILENAME
    target.parent.mkdir(parents=True, exist_ok=True)

    content = (
        f"# DeerFlow admin {label} credentials\n# This file is generated on first boot or password reset.\n# Change the password after login via Settings -> Account,\n# then delete this file.\n#\nemail: {email}\npassword: {password}\n"
    )

    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(content)

    return target.resolve()


__all__ = ["write_initial_credentials"]
