import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_INS_BASE_URL = "https://ins.shenguyun.com"
DEFAULT_INS_RSA_PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAtUDWaqj5TCedQm90z/WQWO5W
ZJRvxwn9YPHGpUt3XpoIB7HJR5IoBrEpvviLdYWOmVwlJNycbpooEqnnOxw/y+1SARyx
VKJLgo+wQSKeh8hT4oPuSAWF7TERvoDSb181k8B9fSdv2xRc3dDKAA4KMpfQRHIaVTVyl
ik6Hqq8VX4dUsPNptEBURuNU1ms1dZARU+iJnKBA8821gZTgGq/HPVnhdu5A41wTFE1Ov
p0olSviQQxWvWPrv+0gqB8aBO+Kmvuaqtgd4PkcPjCCX1UM0H5k/ntPvKZKABEAPhGB+y
6S5YDD9LE+QHNizAIn/yYiUvfrhutRmDEv6Dtry2n5wIDAQAB
-----END PUBLIC KEY-----"""


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
    username: str
    password: str
    base_url: str
    rsa_public_key: str
    access_token: str | None = None


def load_ins_settings(dotenv_path: str = ".env") -> InsSettings:
    load_dotenv_file(dotenv_path)
    access_token = os.getenv("INS_ACCESS_TOKEN", "").strip() or None
    return InsSettings(
        username=os.getenv("INS_USERNAME", "").strip(),
        password=os.getenv("INS_PASSWORD", "").strip(),
        base_url=os.getenv("INS_BASE_URL", DEFAULT_INS_BASE_URL).rstrip("/"),
        rsa_public_key=os.getenv("INS_RSA_PUBLIC_KEY", DEFAULT_INS_RSA_PUBLIC_KEY),
        access_token=access_token,
    )
