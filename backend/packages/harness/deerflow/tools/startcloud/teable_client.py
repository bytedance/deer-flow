"""Shared HTTP client for Teable API."""

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def _load_parent_env():
    """Load parent project .env if Teable vars are not in environment.

    DeerFlow's serve.sh loads agent/.env, but infrastructure vars
    (TEABLE_API_TOKEN, etc.) live in the parent project's .env.
    This fallback ensures tools work even if serve.sh didn't source
    the parent .env (e.g., direct Python execution, tests).
    """
    if os.environ.get("TEABLE_API_TOKEN"):
        return  # already loaded

    # Walk up from this file to find the project root .env
    candidate = Path(__file__).resolve()
    for _ in range(10):
        candidate = candidate.parent
        env_file = candidate / ".env"
        if env_file.is_file():
            try:
                for line in env_file.read_text().splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        key, _, value = line.partition("=")
                        key = key.strip()
                        value = value.strip().strip('"').strip("'")
                        if key.startswith("TEABLE_") and key not in os.environ:
                            os.environ[key] = value
            except OSError:
                pass
            if os.environ.get("TEABLE_API_TOKEN"):
                break


_load_parent_env()

TEABLE_API_URL = os.environ.get("TEABLE_API_URL", "http://localhost:8002")
TEABLE_API_TOKEN = os.environ.get("TEABLE_API_TOKEN", "")
TEABLE_PUBLIC_URL = os.environ.get("TEABLE_PUBLIC_URL", "")


def _headers():
    return {
        "Authorization": f"Bearer {TEABLE_API_TOKEN}",
        "Content-Type": "application/json",
    }


def _request(method, path, body=None, params=None, timeout=30):
    """Make an HTTP request to the Teable API."""
    url = f"{TEABLE_API_URL}/api{path}"
    if params:
        qs = urllib.parse.urlencode(
            {k: v for k, v in params.items() if v is not None},
            doseq=True,
        )
        if qs:
            url += f"?{qs}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, headers=_headers(), method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
            if not raw:
                return {}
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        err_body = e.read().decode()[:500] if e.fp else ""
        return f"HTTP {e.code}: {err_body}"
    except Exception as e:
        return f"Error: {e}"


def teable_get(path, params=None, timeout=30):
    return _request("GET", path, params=params, timeout=timeout)


def teable_post(path, body, timeout=30):
    return _request("POST", path, body, timeout=timeout)


def teable_patch(path, body, timeout=30):
    return _request("PATCH", path, body, timeout=timeout)


def teable_put(path, body, timeout=30):
    return _request("PUT", path, body, timeout=timeout)


def teable_delete(path, params=None, timeout=30):
    return _request("DELETE", path, params=params, timeout=timeout)


def get_public_url():
    """Return the browser-accessible Teable URL."""
    return TEABLE_PUBLIC_URL or TEABLE_API_URL


def check_configured():
    """Return an error message if Teable is not configured, else None."""
    if not TEABLE_API_TOKEN:
        return "Error: TEABLE_API_TOKEN 환경변수가 설정되지 않았습니다. .env 파일에 추가해주세요."
    return None
