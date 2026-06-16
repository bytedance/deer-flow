import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_INS_BASE_URL = "https://ins.shenguyun.com"


def load_dotenv_file(dotenv_path: str = ".env") -> None:
    env_file = Path(dotenv_path)
    if not env_file.exists():
        return

    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or key in os.environ:
            continue

        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]

        os.environ[key] = value


@dataclass(frozen=True)
class InsSettings:
    base_url: str
    access_token: str | None = None


def load_ins_settings(dotenv_path: str = ".env") -> InsSettings:
    load_dotenv_file(dotenv_path)
    access_token = os.getenv("INS_ACCESS_TOKEN", "").strip() or None
    return InsSettings(
        base_url=os.getenv("INS_BASE_URL", DEFAULT_INS_BASE_URL).rstrip("/"),
        access_token=access_token,
    )
