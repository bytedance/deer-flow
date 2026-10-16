"""Operator-only STOP transport and native outbox extension service.

The dedicated role has no submission, artifact, tool or current-user authority.
A signed observed STOP settles only the original native captured task target.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import time
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from deerflow_extension_api import extension
from sqlalchemy import text
from starlette.responses import JSONResponse, Response

from deerflow.mcp.tasks.control import TaskControlRuntime, TaskControlTarget, TaskStopReceipt, canonical, identifier
from deerflow.persistence.workspaces.execution_control import WorkspaceControlRepository
from ecs_executor.job_store import TERMINAL
from ecs_executor.scope import _decode, _encode, _secret

HEADER = "X-DeerFlow-Execution-Control"
PATH = "/_internal/execution-control/stop"
logger = logging.getLogger(__name__)


def _signed(secret, audience, purpose, payload, *, now=None):
    _secret(secret)
    iat = int(time.time() if now is None else now)
    claims = {"version": 1, "purpose": purpose, "aud": audience, "iat": iat, "exp": iat + 60, "payload": payload}
    raw = canonical(claims)
    return _encode(raw) + "." + _encode(hmac.digest(secret, raw, "sha256"))


def _verified(token, secret, audience, purpose, *, now=None):
    _secret(secret)
    if type(token) is not str or len(token) > 8192 or token.count(".") != 1:
        raise ValueError("invalid control token")
    raw, mac = map(_decode, token.split("."))
    if not hmac.compare_digest(hmac.digest(secret, raw, "sha256"), mac):
        raise ValueError("control signature mismatch")
    try:
        claims = json.loads(raw)
        if canonical(claims) != raw or set(claims) != {"version", "purpose", "aud", "iat", "exp", "payload"}:
            raise ValueError("control shape mismatch")
        if type(claims["version"]) is not int or claims["version"] != 1 or claims["purpose"] != purpose or claims["aud"] != audience:
            raise ValueError("control purpose mismatch")
        iat, exp = claims["iat"], claims["exp"]
        clock = time.time() if now is None else now
        if type(iat) is not int or type(exp) is not int or not 0 <= iat < exp or not 1 <= exp - iat <= 300 or iat > clock + 5 or exp <= clock:
            raise ValueError("control token expired")
        return claims["payload"]
    except (TypeError, KeyError, json.JSONDecodeError):
        raise ValueError("invalid control claims") from None


def _intent(operation_id, target):
    if type(operation_id) is not str or re.fullmatch(r"[0-9a-f]{64}", operation_id) is None:
        raise ValueError("invalid stop operation")
    if operation_id != hashlib.sha256(canonical(["mcp_stop", target.digest])).hexdigest():
        raise ValueError("stop operation binding differs")
    return {"operation_id": operation_id, "target": target.as_payload()}


def install_stop_route(server, jobs, *, credential, secret):
    _secret(secret)
    if not jobs.workspace_required or not credential or hmac.compare_digest(secret, jobs.secret):
        raise ValueError("control requires separate scoped operator authority")

    def stop(body):
        if type(body) is not dict or set(body) != {"operation_id", "target"}:
            raise ValueError("invalid stop intent")
        target = TaskControlTarget.from_payload(body["target"])
        _intent(body["operation_id"], target)
        if target.server_name != jobs.native_server_name:
            raise ValueError("control server differs")

        def request_stop(record):
            expected = {
                "user_id": target.user_id,
                "workspace_id": target.workspace_id,
                "thread_id": target.thread_id,
                "incarnation": target.thread_incarnation,
                "run_id": target.run_id,
                "workspace_context": target.as_payload()["workspace_context"],
            }
            if record.get("kind") != "B" or any(record.get(key) != value for key, value in expected.items()):
                raise ValueError("immutable execution target differs")
            if record["state"] not in TERMINAL:
                record["cancel_requested"] = True
                if record["state"] in ("staged", "queued") and not any(record.get(key) for key in ("start_intent", "assignment", "node_id", "generation", "attempt")):
                    record.update(state="cancelled", physical_stopped=True, control_stop_evidence="not_started")
            elif record.get("physical_stopped") is not True:
                # Historical/ordinary terminal state is not physical proof.
                # Ask the existing worker to observe/remove the exact owned
                # object; never infer absence from a terminal ledger value.
                record["cleanup_pending"] = True

        record = jobs.store.mutate(target.remote_task_id, request_stop)
        if record["state"] not in TERMINAL or record.get("physical_stopped") is not True:
            return {"status": "pending"}
        payload = {
            "operation_id": body["operation_id"],
            "target_sha256": target.digest,
            "remote_task_id": target.remote_task_id,
            "spec_digest": record["spec_digest"],
            "observed_at": datetime.now(UTC).isoformat(),
            "evidence": record.get("control_stop_evidence", "physical_absence"),
            "physical_stopped": True,
        }
        return {"status": "stopped", "receipt": _signed(secret, jobs.audience + "/control", "stop_receipt", payload)}

    @server.custom_route(PATH, methods=["POST"])
    async def stop_request(request):
        if not hmac.compare_digest(request.headers.get("authorization", ""), "Bearer " + credential):
            return Response(status_code=404)
        try:
            claims = _verified(request.headers.get(HEADER, ""), secret, jobs.audience + "/control", "stop_intent")
            data = bytearray()
            async for chunk in request.stream():
                data.extend(chunk)
                if len(data) > 8192:
                    return Response(status_code=413)
            body = json.loads(data)
            if canonical(body) != canonical(claims):
                raise ValueError("stop body differs")
            result = await asyncio.to_thread(stop, body)
            return JSONResponse(result, headers={"Cache-Control": "no-store"})
        except (ValueError, TypeError, KeyError, RecursionError):
            return Response(status_code=409)


@dataclass(frozen=True, slots=True)
class ControlRoute:
    url: str
    audience: str
    credential: str = field(repr=False)
    secret: bytes = field(repr=False)

    def __post_init__(self):
        address = urlsplit(self.url)
        if address.scheme not in ("http", "https") or not address.hostname or address.username or address.password or address.query or address.fragment or address.path not in ("", "/"):
            raise ValueError("fixed control origin required")
        identifier(self.audience)
        identifier(self.credential, 4096)
        _secret(self.secret)


class ExecutionControlService:
    def __init__(self, *, routes, poll_seconds=1, client_factory=None):
        if not routes or any(not isinstance(route, ControlRoute) for route in routes.values()) or not 0.1 <= poll_seconds <= 3600:
            raise ValueError("invalid control service configuration")
        for name in routes:
            identifier(name)
        self.routes = dict(routes)
        self.poll_seconds = poll_seconds
        self.client_factory = client_factory or (lambda route: httpx.AsyncClient(base_url=route.url, timeout=30, trust_env=False, follow_redirects=False))
        self.clients = {}
        self.runtime = self.repository = self.task = None
        self.owner = "execution-control:" + uuid4().hex

    async def start(self, deps):
        if self.task is not None or deps.session_factory is None or deps.app_store is None:
            raise ValueError("native SQL and app-scoped lifecycle are required")
        async with deps.session_factory() as session:
            versions = (await session.scalars(text("SELECT version_num FROM alembic_version"))).all()
            if versions != ["0040_mcp_workspace_identity"]:
                raise ValueError("incompatible native control schema")
        self.runtime = deps.app_store.get_or_init(TaskControlRuntime, TaskControlRuntime)
        if self.runtime.ready:
            raise ValueError("only one app control provider is permitted")
        self.repository = WorkspaceControlRepository(deps.session_factory)
        try:
            for name, route in self.routes.items():
                self.clients[name] = self.client_factory(route)
            self.runtime.servers, self.runtime.owner_token = frozenset(self.routes), self.owner
            self.runtime.ready = True
            self.task = asyncio.create_task(self._loop())
        except BaseException:
            await self.stop()
            raise

    async def _loop(self):
        try:
            while True:
                await asyncio.sleep(self.poll_seconds)
                try:
                    await self.run_once()
                except Exception:
                    # Durable leases expire; never log private payloads or
                    # convert an infrastructure error into a STOP receipt.
                    logger.warning("Execution control iteration failed; durable retry retained")
        finally:
            if self.runtime is not None and self.runtime.owner_token == self.owner:
                self.runtime.ready = False

    async def run_once(self, *, now=None):
        if self.runtime is None or not self.runtime.supports(next(iter(self.routes))):
            raise RuntimeError("control service is not running")
        now = now or datetime.now(UTC)
        claims = await self.repository.claim(now=now, owner=self.owner, servers=self.routes, limit=1)
        for claim in claims:
            route, client = self.routes[claim.target.server_name], self.clients[claim.target.server_name]
            try:
                body = _intent(claim.operation_id, claim.target)
                async with asyncio.timeout(30):
                    response = await client.post(
                        PATH, content=canonical(body), headers={"Authorization": "Bearer " + route.credential, "Content-Type": "application/json", HEADER: _signed(route.secret, route.audience, "stop_intent", body)}, follow_redirects=False
                    )
                response.raise_for_status()
                if len(response.content) > 16384:
                    raise ValueError("control response too large")
                result = response.json()
                if result == {"status": "pending"}:
                    await self.repository.defer(claim, now=max(now, datetime.now(UTC)))
                    continue
                if set(result) != {"status", "receipt"} or result["status"] != "stopped":
                    raise ValueError("control response invalid")
                proof = _verified(result["receipt"], route.secret, route.audience, "stop_receipt")
                if (
                    set(proof) != {"operation_id", "target_sha256", "remote_task_id", "spec_digest", "observed_at", "evidence", "physical_stopped"}
                    or proof["physical_stopped"] is not True
                    or proof["evidence"] not in ("physical_absence", "not_started")
                    or re.fullmatch(r"[0-9a-f]{64}", proof["spec_digest"]) is None
                ):
                    raise ValueError("invalid physical STOP proof")
                observed = datetime.fromisoformat(proof["observed_at"])
                if observed.tzinfo is None or abs((datetime.now(UTC) - observed).total_seconds()) > 300:
                    raise ValueError("invalid STOP observation clock")
                receipt = TaskStopReceipt(**{key: value for key, value in proof.items() if key not in ("physical_stopped", "observed_at")}, observed_at=observed)
                await self.repository.settle_stop(claim, receipt, now=max(now, datetime.now(UTC)))
            except (httpx.HTTPError, ValueError, TypeError, KeyError, TimeoutError):
                await self.repository.defer(claim, now=max(now, datetime.now(UTC)), seconds=5)

    async def stop(self):
        if self.runtime is not None and self.runtime.owner_token == self.owner:
            self.runtime.ready = False
        if self.task is not None:
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task
            self.task = None
        for client in self.clients.values():
            await client.aclose()
        self.clients.clear()


@extension(api="0.2.0", name="ecs-execution-control")
def install(registry, config):
    routes = {name: ControlRoute(url=value["url"], audience=value["audience"], credential=os.environ[value["credential_env"]], secret=os.environ[value["secret_env"]].encode()) for name, value in config["routes"].items()}
    registry.service(ExecutionControlService(routes=routes, poll_seconds=config.get("poll_seconds", 1)))
