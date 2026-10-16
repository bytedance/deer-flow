"""Bounded HMAC submission scopes shared by the gateway and remote verifier.

The scope proves a trusted run's submission intent, not current task ownership.
Status/cancel must authorize against the remote task's persisted owner.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

from deerflow.authz.workspace import WorkspaceContext

SCOPE_HEADER = "X-DeerFlow-Execution-Scope"
MAX_TTL_SECONDS = 300
MAX_TOKEN_BYTES = 8192
MAX_ARGUMENT_BYTES = 262144
WORKSPACE_SCOPE_VERSION = 2
_FIELDS = {"aud", "user_id", "thread_id", "incarnation", "run_id", "operation", "iat", "exp", "args_sha256"}


def _secret(secret: bytes) -> None:
    if not isinstance(secret, bytes) or len(secret) < 32:
        raise ValueError("Execution scope requires an operator secret of at least 32 bytes")


def _identifier(value: Any) -> None:
    if not isinstance(value, str) or not 1 <= len(value) <= 255 or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("Invalid execution scope identifier")


def _integer(value: Any) -> None:
    if type(value) is not int or not 0 <= value <= 2**53 - 1:
        raise ValueError("Invalid execution scope timestamp")


def _json(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")
    except (ValueError, TypeError, RecursionError):
        raise ValueError("Invalid execution scope JSON") from None


def arguments_sha256(arguments: dict[str, Any]) -> str:
    """Hash strict JSON arguments with bounded size and nesting depth."""

    def check(value: Any, depth: int = 0) -> None:
        if depth > 32:
            raise ValueError("Execution scope arguments exceed nesting limit")
        if isinstance(value, dict):
            for key, child in value.items():
                if not isinstance(key, str):
                    raise ValueError("Execution scope arguments require string keys")
                check(child, depth + 1)
        elif isinstance(value, list):
            for child in value:
                check(child, depth + 1)
        elif value is not None and type(value) not in (str, int, float, bool):
            raise ValueError("Execution scope arguments must be JSON")

    if not isinstance(arguments, dict):
        raise ValueError("Execution scope arguments must be an object")
    check(arguments)
    encoded = _json(arguments)
    if len(encoded) > MAX_ARGUMENT_BYTES:
        raise ValueError("Execution scope arguments exceed size limit")
    return hashlib.sha256(encoded).hexdigest()


def _workspace_claims(context: WorkspaceContext, user_id: str) -> dict[str, Any]:
    if type(context) is not WorkspaceContext or context.actor_user_id != user_id:
        raise ValueError("Execution scope workspace actor mismatch")
    return asdict(context)


def _validate(claims: Any) -> None:
    if not isinstance(claims, dict):
        raise ValueError("Invalid execution scope claims")
    scoped = set(claims) == _FIELDS | {"version", "workspace_context"}
    if not scoped and set(claims) != _FIELDS:
        raise ValueError("Invalid execution scope claims")
    if scoped:
        if type(claims["version"]) is not int or claims["version"] != WORKSPACE_SCOPE_VERSION:
            raise ValueError("Unsupported execution scope version")
        value = claims["workspace_context"]
        if not isinstance(value, dict):
            raise ValueError("Invalid execution scope workspace")
        try:
            context = WorkspaceContext(**value)
        except (TypeError, ValueError):
            raise ValueError("Invalid execution scope workspace") from None
        _workspace_claims(context, claims["user_id"])
        _identifier(claims["incarnation"])
    for name in ("aud", "user_id", "thread_id", "run_id", "operation"):
        _identifier(claims[name])
    if claims["incarnation"] is not None:
        _identifier(claims["incarnation"])
    _integer(claims["iat"])
    _integer(claims["exp"])
    if not 1 <= claims["exp"] - claims["iat"] <= MAX_TTL_SECONDS:
        raise ValueError("Invalid execution scope lifetime")
    if not isinstance(claims["args_sha256"], str) or re.fullmatch(r"[0-9a-f]{64}", claims["args_sha256"]) is None:
        raise ValueError("Invalid execution scope argument digest")


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode(value: str) -> bytes:
    if re.fullmatch(r"[A-Za-z0-9_-]+", value) is None:
        raise ValueError("Invalid execution scope encoding")
    try:
        decoded = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    except ValueError:
        raise ValueError("Invalid execution scope encoding") from None
    if _encode(decoded) != value:
        raise ValueError("Noncanonical execution scope encoding")
    return decoded


def mint_execution_scope(
    *,
    secret: bytes,
    audience: str,
    user_id: str,
    thread_id: str,
    incarnation: str | None,
    run_id: str,
    operation: str,
    arguments: dict[str, Any],
    workspace_context: WorkspaceContext | None = None,
    now: int | None = None,
    ttl_seconds: int = 60,
) -> str:
    """Sign a short-lived, argument-bound submission from trusted runtime values."""
    _secret(secret)
    issued = int(time.time()) if now is None else now
    _integer(issued)
    if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= MAX_TTL_SECONDS:
        raise ValueError("Invalid execution scope lifetime")
    claims = {"aud": audience, "user_id": user_id, "thread_id": thread_id, "incarnation": incarnation, "run_id": run_id, "operation": operation, "iat": issued, "exp": issued + ttl_seconds, "args_sha256": arguments_sha256(arguments)}
    if workspace_context is not None:
        claims.update(version=WORKSPACE_SCOPE_VERSION, workspace_context=_workspace_claims(workspace_context, user_id))
    _validate(claims)
    payload = _encode(_json(claims))
    signature = _encode(hmac.digest(secret, payload.encode("ascii"), "sha256"))
    token = f"{payload}.{signature}"
    if len(token) > MAX_TOKEN_BYTES:
        raise ValueError("Execution scope exceeds size limit")
    return token


@dataclass(frozen=True, slots=True)
class ExecutionIdentity:
    """Authenticated locators only; contains no token-asserted workspace grant."""

    user_id: str
    thread_id: str
    incarnation: str | None
    run_id: str


def verify_execution_scope(
    token: str,
    *,
    secret: bytes,
    authenticated_user_id: str,
    arguments: dict[str, Any],
    expected_audience: str,
    expected_operation: str,
    expected_workspace_context: WorkspaceContext | None = None,
    workspace_resolver: Callable[[ExecutionIdentity], WorkspaceContext] | None = None,
    now: int | None = None,
) -> dict[str, Any]:
    """Verify before execution, binding separate authenticated owner and arguments.

    expected_workspace_context must be independently authorized by the receiver,
    never reconstructed from this token or the browser's current selection.
    A resolver receives only authenticated locators after all cryptographic and
    argument checks, and must return independently authorized native identity.
    Version 2 is refused by callers without that expectation or resolver; callers
    with one refuse legacy signatures. Matching versions do not prove live membership.

    Never return or log the token on failure. Remote task creation must persist
    the verified owner/scope and use that record to authorize later operations.
    """
    _secret(secret)
    if not isinstance(token, str) or not 1 <= len(token) <= MAX_TOKEN_BYTES or token.count(".") != 1:
        raise ValueError("Invalid execution scope token")
    payload, encoded_signature = token.split(".")
    decoded_payload = _decode(payload)
    signature = _decode(encoded_signature)
    if not hmac.compare_digest(signature, hmac.digest(secret, payload.encode("ascii"), "sha256")):
        raise ValueError("Invalid execution scope signature")
    try:
        claims = json.loads(decoded_payload)
    except (ValueError, UnicodeError, RecursionError):
        raise ValueError("Invalid execution scope claims") from None
    _validate(claims)
    # Reject duplicate fields, noncanonical numbers and alternate JSON encodings.
    if _json(claims) != decoded_payload:
        raise ValueError("Noncanonical execution scope claims")
    current = int(time.time()) if now is None else now
    _integer(current)
    if not claims["iat"] <= current < claims["exp"]:
        raise ValueError("Execution scope is expired or not yet valid")
    if claims["aud"] != expected_audience or claims["operation"] != expected_operation or claims["user_id"] != authenticated_user_id:
        raise ValueError("Execution scope authority mismatch")
    if not hmac.compare_digest(claims["args_sha256"], arguments_sha256(arguments)):
        raise ValueError("Execution scope arguments mismatch")
    if workspace_resolver is not None:
        if expected_workspace_context is not None or "workspace_context" not in claims:
            raise ValueError("Execution scope requires one workspace authorization source")
        expected_workspace_context = workspace_resolver(ExecutionIdentity(claims["user_id"], claims["thread_id"], claims["incarnation"], claims["run_id"]))
        if type(expected_workspace_context) is not WorkspaceContext:
            raise ValueError("Execution scope resolver requires workspace authorization")
    if expected_workspace_context is None:
        if "workspace_context" in claims:
            raise ValueError("Execution scope workspace authorization is required")
    elif claims.get("workspace_context") != _workspace_claims(expected_workspace_context, authenticated_user_id):
        raise ValueError("Execution scope workspace mismatch")
    return claims


def verify_native_execution_scope(token: str, *, engine, secret: bytes, authenticated_user_id: str, arguments: dict[str, Any], expected_audience: str, expected_operation: str) -> dict[str, Any]:
    """Native SQL submission preflight; not a worker start/publication grant.

    Accepts only v2 submit intent. Callers must fence native task commitment,
    ledger identity, physical launch and publication separately. No HTTP endpoint
    is enabled by this function and no database row or ambient scope is mutated.
    """
    from ecs_executor.native_authority import NativeSubmissionAuthority

    if expected_operation != "submit":
        raise ValueError("Native execution preflight only accepts submit")
    return verify_execution_scope(
        token, secret=secret, authenticated_user_id=authenticated_user_id, arguments=arguments, expected_audience=expected_audience, expected_operation=expected_operation, workspace_resolver=NativeSubmissionAuthority(engine).resolve
    )


def mint_management_scope(*, secret: bytes, audience: str, user_id: str, task_id: str, operation: str, now: int | None = None, ttl_seconds: int = 60) -> str:
    """Owner/task capability for the native poller, which has no active run."""
    _secret(secret)
    issued = int(time.time()) if now is None else now
    for value in (audience, user_id, task_id):
        _identifier(value)
    _integer(issued)
    if operation not in {"status", "cancel"} or type(ttl_seconds) is not int or not 1 <= ttl_seconds <= MAX_TTL_SECONDS:
        raise ValueError("Invalid management scope")
    claims = {"aud": audience, "user_id": user_id, "task_id": task_id, "operation": operation, "iat": issued, "exp": issued + ttl_seconds, "args_sha256": arguments_sha256({"task_id": task_id})}
    payload = _encode(_json(claims))
    return payload + "." + _encode(hmac.digest(secret, payload.encode("ascii"), "sha256"))


def verify_management_scope(token: str, *, secret: bytes, authenticated_user_id: str, arguments: dict[str, Any], expected_audience: str, expected_operation: str, now: int | None = None) -> dict[str, Any]:
    _secret(secret)
    if not isinstance(token, str) or not 1 <= len(token) <= MAX_TOKEN_BYTES or token.count(".") != 1:
        raise ValueError("Invalid management scope")
    payload, signature = token.split(".")
    encoded = _decode(payload)
    if not hmac.compare_digest(_decode(signature), hmac.digest(secret, payload.encode("ascii"), "sha256")):
        raise ValueError("Invalid management signature")
    try:
        claims = json.loads(encoded)
    except (ValueError, UnicodeError, RecursionError):
        raise ValueError("Invalid management claims") from None
    if not isinstance(claims, dict) or set(claims) != {"aud", "user_id", "task_id", "operation", "iat", "exp", "args_sha256"} or _json(claims) != encoded:
        raise ValueError("Invalid management claims")
    for name in ("aud", "user_id", "task_id"):
        _identifier(claims[name])
    _integer(claims["iat"])
    _integer(claims["exp"])
    current = int(time.time()) if now is None else now
    _integer(current)
    if not 1 <= claims["exp"] - claims["iat"] <= MAX_TTL_SECONDS or not claims["iat"] <= current < claims["exp"]:
        raise ValueError("Invalid management lifetime")
    if claims["aud"] != expected_audience or claims["user_id"] != authenticated_user_id or claims["operation"] != expected_operation or expected_operation not in {"status", "cancel"}:
        raise ValueError("Management authority mismatch")
    if arguments != {"task_id": claims["task_id"]} or claims["args_sha256"] != arguments_sha256(arguments):
        raise ValueError("Management arguments mismatch")
    return claims
