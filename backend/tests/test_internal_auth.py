import os
import subprocess
import sys


def _run_internal_auth_snippet(code: str, *, token: str | None = None) -> str:
    env = os.environ.copy()
    if token is None:
        env.pop("DEER_FLOW_INTERNAL_AUTH_TOKEN", None)
    else:
        env["DEER_FLOW_INTERNAL_AUTH_TOKEN"] = token
    result = subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        capture_output=True,
        env=env,
        text=True,
    )
    return result.stdout.strip()


def test_internal_auth_token_env_is_stable_across_processes():
    token = "shared-internal-auth-token"

    emitted = _run_internal_auth_snippet(
        "from app.gateway.internal_auth import create_internal_auth_headers; print(create_internal_auth_headers()['X-DeerFlow-Internal-Token'])",
        token=token,
    )
    validated = _run_internal_auth_snippet(
        f"from app.gateway.internal_auth import is_valid_internal_auth_token; print(is_valid_internal_auth_token({emitted!r}))",
        token=token,
    )

    assert emitted == token
    assert validated == "True"


def test_internal_auth_rejects_different_configured_token():
    emitted = _run_internal_auth_snippet(
        "from app.gateway.internal_auth import create_internal_auth_headers; print(create_internal_auth_headers()['X-DeerFlow-Internal-Token'])",
        token="worker-a-token",
    )
    validated = _run_internal_auth_snippet(
        f"from app.gateway.internal_auth import is_valid_internal_auth_token; print(is_valid_internal_auth_token({emitted!r}))",
        token="worker-b-token",
    )

    assert validated == "False"
