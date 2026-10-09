"""Fixed-node capabilities for existing native Gateway admissions."""

import asyncio
import hmac
import json
import logging
import os
import time
import uuid
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from sqlalchemy import Column, MetaData, String, Table, select
from sqlalchemy.dialects.postgresql import insert
from starlette.responses import JSONResponse
from starlette.routing import Route

from ecs_executor.dispatch import PROTOCOL, WORKER_VERSION
from ecs_executor.schema import SCHEMA_REVISION
from ecs_executor.scope import arguments_sha256, mint_execution_scope, verify_execution_scope


def seal_native_secrets(native, node, secret, context):
    from deerflow.persistence.channel_connections.sql import ChannelCredentialCipher
    from deerflow.runtime.secret_context import extract_request_secrets

    values = extract_request_secrets(context)
    if not values:
        return None
    identity = {key: native[key] for key in ("user_id", "thread_id", "incarnation", "run_id")}
    return ChannelCredentialCipher.from_key(secret).encrypt_text(json.dumps({"identity": identity, "node": node, "secrets": values}, separators=(",", ":")))


def open_native_secrets(native, node, secret, carrier):
    from deerflow.persistence.channel_connections.sql import ChannelCredentialCipher
    from deerflow.runtime.secret_context import extract_request_secrets

    if carrier is None:
        return {}
    try:
        payload = json.loads(ChannelCredentialCipher.from_key(secret).decrypt_text(carrier))
        identity = {key: native[key] for key in ("user_id", "thread_id", "incarnation", "run_id")}
        if payload["identity"] != identity or payload["node"] != node:
            raise ValueError
        return extract_request_secrets(payload)
    except Exception:
        raise ValueError("Native encrypted carrier denied") from None


def _arguments(job):
    return {**{key: job[key] for key in ("id", "node_id", "generation", "worker_owner", "native")}, "node_budget": job.get("node_budget")}


def sign_native_launch(job, secret):
    native = job["native"]
    return mint_execution_scope(
        secret=secret.encode(), audience=job["node_id"], user_id=native["user_id"], thread_id=native["thread_id"], incarnation=native["incarnation"], run_id=native["run_id"], operation="native_launch", arguments=_arguments(job)
    )


def verify_native_launch(job, token, secret):
    try:
        native = job["native"]
        claims = verify_execution_scope(token, secret=secret.encode(), authenticated_user_id=native["user_id"], arguments=_arguments(job), expected_audience=job["node_id"], expected_operation="native_launch")
        if any(claims[key] != native[key] for key in ("user_id", "thread_id", "incarnation", "run_id")):
            raise ValueError("Native identity mismatch")
        return native
    except (ValueError, KeyError, TypeError):
        raise ValueError("Native launch capability denied") from None


logger = logging.getLogger(__name__)


_AFFINITY_METADATA = MetaData()
_AFFINITIES = Table(
    "ecs_native_affinities",
    _AFFINITY_METADATA,
    Column("user_id", String(255), primary_key=True),
    Column("thread_id", String(255), primary_key=True),
    Column("incarnation", String(255), primary_key=True),
    Column("node_id", String(64), nullable=False),
)


def _affinity(store, user_id, thread_id, incarnation, *, node_id=None):
    with store.engine.begin() as connection:
        conditions = (_AFFINITIES.c.user_id == user_id, _AFFINITIES.c.thread_id == thread_id, _AFFINITIES.c.incarnation == incarnation)
        if node_id is not None:
            connection.execute(insert(_AFFINITIES).values(user_id=user_id, thread_id=thread_id, incarnation=incarnation, node_id=node_id).on_conflict_do_nothing())
        value = connection.execute(select(_AFFINITIES.c.node_id).where(*conditions)).scalar_one_or_none()
        if node_id is not None and value != node_id:
            raise ValueError("Native thread incarnation affinity changed")
        return value


class NativeDispatchHost:
    """Placement/queue ownership only; graph execution belongs to native Gateway."""

    def __init__(self, app, pool, config, credentials):
        self.app, self.pool, self.config, self.credentials = app, pool, config, credentials
        self.task = None
        self.quiescing = False

    async def quiesce(self):
        self.quiescing = True

    async def prepare_notification(self, notification):
        from ecs_executor.dependencies import prepare_notification

        return await prepare_notification(self, notification)

    async def reconcile_dependency_waits(self, source_run_ids):
        from ecs_executor.dependencies import maintain_waits

        return await maintain_waits(self, source_run_ids=source_run_ids)

    async def acknowledge_continuation(self, wait, run_id):
        from ecs_executor.dependencies import source_job

        if wait.get("notification_only"):
            return
        job = await asyncio.to_thread(source_job, self.pool.store, wait["source_run_id"])
        await asyncio.to_thread(self.pool.store.mutate, job["id"], lambda row: row["dependency_wait"].update(continuation_run_id=run_id))

    async def admit_native(self, record, snapshot_factory):
        if self.quiescing:
            raise RuntimeError("Native dispatcher is quiescing")
        # Origin is server-stamped before admission, never external metadata.
        origin = (record.metadata or {}).get("deerflow_origin") or {}
        node = None
        if record.user_id:
            thread = await self.app.state.thread_store.get(record.thread_id, user_id=record.user_id)
            if thread is not None:
                node = await asyncio.to_thread(_affinity, self.pool.store, record.user_id, record.thread_id, thread["incarnation"])
        if node is None and getattr(self, "browser_control", None) is None and origin.get("kind") not in self.config.get("remote_origins", ["schedule"]):
            return False
        node = node or self.config["native_node"]
        snapshot = await snapshot_factory(transport_node=node, transport_secret=self.credentials[node])
        wait = snapshot["execution"].get("dependency_continuation")
        scheduled = snapshot["execution"].get("scheduled_task_runtime")
        if wait is not None and not wait.get("notification_only") and scheduled is not None:
            await self.app.state.scheduled_task_run_repo.transfer_dependency_run(
                task_id=scheduled["task_id"], occurrence_id=scheduled["occurrence_id"], user_id=record.user_id, source_run_id=wait["source_run_id"], continuation_run_id=record.run_id
            )
        if not record.user_id:
            raise ValueError("Remote native admission requires an authenticated owner")
        node = node or self.config["native_node"]
        profile = self.config["profile"]
        job = await asyncio.to_thread(
            self.pool.store.create,
            namespace="native-C",
            request_key=record.run_id,
            spec_digest=arguments_sha256(snapshot),
            record={
                "kind": "C",
                "node_budget": self.pool.nodes[node].model_dump(mode="json"),
                "native": snapshot,
                "affinity_node": node,
                "spec": {"profile": profile},
                "profile": self.config["profiles"][profile],
                "staged_deadline": time.time() + 120,
                "cancel_requested": False,
                "physical_stopped": False,
            },
        )
        await asyncio.to_thread(_affinity, self.pool.store, record.user_id, record.thread_id, snapshot["incarnation"], node_id=node)
        await self.app.state.run_manager.handoff_pending(record.run_id, owner_worker_id="dispatch:" + job["id"])
        await asyncio.to_thread(self.pool.store.mutate, job["id"], lambda row: row.update(state="queued"))
        return True

    async def refuse(self, job):
        if job.get("settlement_kind") == "refusal":
            if job.get("physical_stopped") and not job.get("settlement_pending"):
                return job
            await self.settle_refusal(job)
            return await asyncio.to_thread(self.pool.store.get, job["id"])
        native = job["native"]
        row = await self.app.state.run_store.get(native["run_id"], user_id=native["user_id"])
        if row is None or row.get("owner_worker_id") != "dispatch:" + job["id"] or row["status"] != "pending":
            raise ValueError("Native refusal lacks a no-adoption proof")

        def intent(value):
            if any(value.get(key) != job.get(key) for key in ("node_id", "worker_owner", "generation")) or value["state"] not in {"starting", "uncertain"}:
                raise RuntimeError("Native refusal assignment changed")
            value.update(state="uncertain", settlement_kind="refusal", settlement_pending=True, settlement_error="Native worker refused the admitted execution snapshot", settlement_cancel_action=None)

        pending = await asyncio.to_thread(self.pool.store.mutate, job["id"], intent)
        await self.settle_refusal(pending)
        return await asyncio.to_thread(self.pool.store.get, job["id"])

    async def settle_refusal(self, job):
        native, owner = job["native"], "dispatch:" + job["id"]
        store = self.app.state.run_store
        for _ in range(2):
            row = await store.get(native["run_id"], user_id=native["user_id"])
            if row is None or row.get("owner_worker_id") != owner:
                await asyncio.to_thread(self.pool.store.mutate, job["id"], lambda value: value.update(state="uncertain", settlement_pending=False))
                return
            if row["status"] == "pending":
                await store.renew_lease(native["run_id"], owner_worker_id=owner, lease_expires_at=(datetime.now(UTC) + timedelta(seconds=120)).isoformat())
                action = row.get("cancel_action")
                error = None if action else "Native worker refused the admitted execution snapshot"
                job = await asyncio.to_thread(self.pool.store.mutate, job["id"], lambda value: value.update(settlement_error=error, settlement_cancel_action=action))
                # The intent outlives either native commit or lost END/report.
                await store.finish_dispatch_pending(native["run_id"], owner_worker_id=owner, error=error)
                continue
            action, error = job.get("settlement_cancel_action"), job.get("settlement_error")
            matching = (action is not None and row["status"] == "interrupted" and row.get("cancel_action") == action) or (action is None and row["status"] == "error" and row.get("error") == error and not row.get("cancel_action"))
            if not matching:
                await asyncio.to_thread(self.pool.store.mutate, job["id"], lambda value: value.update(state="uncertain", settlement_pending=False))
                return
            await self.app.state.stream_bridge.publish_end(native["run_id"])
            await asyncio.to_thread(self.pool.store.mutate, job["id"], lambda value: value.update(state="cancelled" if action else "failed", error=error, physical_stopped=True, settlement_pending=False))
            return
        raise RuntimeError("Native refusal commit unconfirmed")

    async def settle_queued_cancel(self, job):
        if job.get("settlement_kind") == "refusal":
            return await self.settle_refusal(job)
        if job.get("start_intent") or job["state"] != "cancelled":
            raise RuntimeError("Queued native settlement lost its no-start fence")
        native = job["native"]
        owner = "dispatch:" + job["id"]
        store = self.app.state.run_store
        row = await store.get(native["run_id"], user_id=native["user_id"])
        if row is not None and row.get("owner_worker_id") == owner and row.get("cancel_action") == job["settlement_cancel_action"]:
            if row["status"] == "pending":
                await store.renew_lease(native["run_id"], owner_worker_id=owner, lease_expires_at=(datetime.now(UTC) + timedelta(seconds=120)).isoformat())
                await store.finish_dispatch_pending(native["run_id"], owner_worker_id=owner)
                row = await store.get(native["run_id"], user_id=native["user_id"])
            if row is not None and row.get("owner_worker_id") == owner and row["status"] == "interrupted" and row.get("cancel_action") == job["settlement_cancel_action"]:
                # This exact never-started dispatch owns END. A crash after
                # native commit or END publication can safely retry it.
                await self.app.state.stream_bridge.publish_end(native["run_id"])
            elif row is not None and row.get("owner_worker_id") == owner and row["status"] == "pending":
                raise RuntimeError("Queued native cancellation commit unconfirmed")
        await asyncio.to_thread(self.pool.store.mutate, job["id"], lambda value: value.update(settlement_pending=False))

    async def maintain(self):
        from ecs_executor.dependencies import maintain_waits

        if getattr(self.app.state, "run_manager", None) is not None:
            await maintain_waits(self)
        store = self.app.state.run_store
        pending = await asyncio.to_thread(self.pool.store.list_native_settlement_pending)
        for job in pending:
            try:
                await self.settle_queued_cancel(job)
            except Exception:
                # One pending END cannot starve unrelated queued lease renewal.
                logger.warning("Queued native settlement remains pending")
        jobs = await asyncio.to_thread(self.pool.store.list_active, kind="C")
        for job in jobs:
            if job.get("kind") != "C":
                continue
            native = job["native"]
            row = await store.get(native["run_id"], user_id=native["user_id"])
            dispatch_owner = "dispatch:" + job["id"]
            if row is None:
                await asyncio.to_thread(self.pool.store.mutate, job["id"], lambda value: value.update(cancel_requested=True))
                continue
            if row.get("cancel_action"):
                await asyncio.to_thread(self.pool.store.mutate, job["id"], lambda value: value.update(cancel_requested=True))
                # Queued/staged is fenced from a concurrent pool claim by the
                # store CAS; owner/status CAS separately excludes adoption.
                if job["state"] in {"staged", "queued"}:

                    def stop(value):
                        if value["state"] in {"staged", "queued"} and not value.get("start_intent"):
                            value.update(state="cancelled", physical_stopped=True, settlement_pending=True, settlement_cancel_action=row["cancel_action"])

                    stopped = await asyncio.to_thread(self.pool.store.mutate, job["id"], stop)
                    if stopped.get("settlement_pending"):
                        try:
                            await self.settle_queued_cancel(stopped)
                        except Exception:
                            logger.warning("Queued native settlement remains pending")
                continue
            if row["status"] not in {"pending", "running"}:
                # Native terminal outcomes are settled only after the adopting
                # worker task drains. They are not cancellation requests.
                continue
            if row.get("owner_worker_id") == dispatch_owner:
                expiry = (datetime.now(UTC) + timedelta(seconds=120)).isoformat()
                await store.renew_lease(native["run_id"], owner_worker_id=dispatch_owner, lease_expires_at=expiry)
                if job["state"] == "staged":
                    await asyncio.to_thread(self.pool.store.mutate, job["id"], lambda value: value.update(state="queued") if value["state"] == "staged" else None)
            elif job["state"] == "staged" and job["staged_deadline"] < time.time():
                await asyncio.to_thread(self.pool.store.mutate, job["id"], lambda value: value.update(state="failed", physical_stopped=True, error="Native admission was not handed off") if value["state"] == "staged" else None)

    async def run(self):
        while True:
            try:
                await self.maintain()
            except Exception:
                logger.exception("Native dispatch queue maintenance failed")
            await asyncio.sleep(2)

    async def start(self):
        await self.maintain()
        self.task = asyncio.create_task(self.run())

    async def stop(self):
        if self.task is not None:
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task
        self.pool.store.engine.dispose()


def install_native_dispatch(app, host):
    root = Path(host.config["artifact_root"])
    marker = root / "pool-mount-id"
    root.mkdir(parents=True, exist_ok=True)
    if not marker.exists():
        temporary = root / (".mount-" + uuid.uuid4().hex)
        temporary.write_text(uuid.uuid4().hex, encoding="ascii")
        try:
            try:
                os.link(temporary, marker)
            except FileExistsError:
                pass
        finally:
            temporary.unlink()
    mount_id = marker.read_text(encoding="ascii")
    host.mount_id = mount_id

    async def dispatch(request):
        try:
            node = request.path_params["node"]
            credential = host.credentials.get(node)
            if not credential or not hmac.compare_digest(request.headers.get("authorization", ""), "Bearer " + credential):
                raise ValueError("Worker credential denied")
            args = await request.json()
            if (
                args.get("schema_revision") != SCHEMA_REVISION
                or args.get("protocol") != PROTOCOL
                or args.get("worker_version") != host.pool.nodes[node].worker_version
                or args.get("mount_id") != mount_id
                or not isinstance(args.get("owner"), str)
                or not args["owner"]
            ):
                raise ValueError("Worker protocol mismatch")
            operation = request.path_params["operation"]
            if operation == "bootstrap":
                await host.maintain()
                return JSONResponse({"schema_revision": SCHEMA_REVISION, "renewed": True})
            if operation == "poll":
                await host.maintain()
                owned = await asyncio.to_thread(host.pool.owned, node, args["owner"], kind="C")
                claim = None if host.quiescing else await asyncio.to_thread(host.pool.claim, node, args["owner"], kind="C")
                return JSONResponse(
                    {
                        "schema_revision": SCHEMA_REVISION,
                        "owned": [{"job": job, "capability": sign_native_launch(job, credential)} for job in owned],
                        "claim": {"job": claim, "capability": sign_native_launch(claim, credential)} if claim else None,
                    }
                )
            if operation == "notification":
                from app.gateway.services import launch_mcp_task_notification_run
                from app.mcp_tasks.errors import PermanentNotificationError
                from deerflow.runtime.runs.manager import ConflictError

                notification = args["notification"]
                owner, thread_id = notification["owner_user_id"], notification["thread_id"]
                claims = verify_execution_scope(args["capability"], secret=credential.encode(), authenticated_user_id=owner, arguments=notification, expected_audience=node, expected_operation="native_notification")
                thread = await host.app.state.thread_store.get(thread_id, user_id=owner)
                if thread is None or claims["thread_id"] != thread_id or claims["incarnation"] != thread["incarnation"]:
                    raise ValueError("Native notification identity mismatch")
                # Global native notification claims may be owned by any peer.
                # Authenticate the sender, then resolve placement centrally;
                # the sender node is never evidence of the source Run's node.
                task = await host.app.state.mcp_task_repo.get(notification["task_id"], user_id=owner, thread_id=thread_id, thread_incarnation=thread["incarnation"])
                if (
                    task is None
                    or task.get("run_id") != args["source_run_id"]
                    or claims["run_id"] != (task.get("run_id") or "mcp-task:" + notification["task_id"])
                    or task.get("dispatch_version") != notification["dispatch_version"]
                    or task.get("dispatch_attempt") != notification["dispatch_attempt"]
                    or task.get("dispatch_event") != notification["event"]
                    or task.get("notification_status") != "launching"
                ):
                    raise ValueError("Native notification reservation mismatch")
                try:
                    return JSONResponse(await launch_mcp_task_notification_run(app=host.app, **notification))
                except PermanentNotificationError:
                    return JSONResponse({"error": "Notification permanently rejected"}, status_code=410)
                except ConflictError:
                    return JSONResponse({"error": "Notification waiting for native dependencies"}, status_code=409)
            job = await asyncio.to_thread(host.pool.store.get, args["job_id"])
            if job.get("kind") != "C" or job.get("node_id") != node or job.get("worker_owner") != args["owner"] or job.get("generation") != args.get("generation"):
                raise ValueError("Native assignment mismatch")
            if operation == "wait":
                from ecs_executor.dependencies import persist_wait

                return JSONResponse({"waiting": await persist_wait(host, job)})
            if operation == "refuse":
                return JSONResponse(await host.refuse(job))
            if operation == "get":
                return JSONResponse(job)
            if operation == "report":
                return JSONResponse(await asyncio.to_thread(host.pool.report, node, args["owner"], job["id"], job["generation"], args["changes"], args["expected"]))
            raise ValueError("Unknown native worker operation")
        except (ValueError, KeyError, TypeError):
            return JSONResponse({"error": "Native worker denied"}, status_code=403)
        except RuntimeError:
            return JSONResponse({"error": "Native worker snapshot changed"}, status_code=409)

    app.router.routes.insert(0, Route("/api/native-workers/{node}/{operation}", dispatch, methods=["POST"]))


class NativeWorkerHost:
    # Role policy belongs to the executor; native Scheduler stays configured
    # for owner-bound tools/completion, with claims owned by control Gateways.
    scheduler_dispatch_enabled = False

    def __init__(self, app, config):
        self.app, self.config = app, config
        import fcntl

        self.node_lock = (Path(config["artifact_root"]) / ("native-node-" + config["node_id"] + ".lock")).open("a")
        try:
            fcntl.flock(self.node_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            self.node_lock.close()
            raise
        self.owner, self.task = uuid.uuid4().hex, None
        self.active = {}
        self.stop_tasks = {}
        self.closing = False
        self.quiescing = False
        self.adoption_lock = asyncio.Lock()
        self.adopting = None
        self.executions = {}
        self.cleanup_task = None
        self.secret = os.environ[config["credential_env"]]
        self.mount_id = (Path(config["artifact_root"]) / "pool-mount-id").read_text(encoding="ascii")
        self.client = httpx.AsyncClient(headers={"Authorization": "Bearer " + self.secret, "X-DeerFlow-Internal-Token": os.environ["DEER_FLOW_INTERNAL_AUTH_TOKEN"]}, timeout=30)

    async def persist_dependency_wait(self, record):
        for job, owned in self.executions.values():
            if owned.run_id == record.run_id:
                return (await self.request("wait", job_id=job["id"], generation=job["generation"]))["waiting"]
        raise RuntimeError("Native dependency source assignment unavailable")

    async def forward_notification(self, notification):
        from app.mcp_tasks.errors import PermanentNotificationError
        from deerflow.runtime.runs.manager import ConflictError

        thread = await self.app.state.thread_store.get(notification["thread_id"], user_id=notification["owner_user_id"])
        task = await self.app.state.mcp_task_repo.get(notification["task_id"], user_id=notification["owner_user_id"], thread_id=notification["thread_id"], thread_incarnation=thread.get("incarnation") if thread else None)
        if task is None:
            raise PermanentNotificationError("Native notification source unavailable")
        capability = mint_execution_scope(
            secret=self.secret.encode(),
            audience=self.config["node_id"],
            user_id=notification["owner_user_id"],
            thread_id=notification["thread_id"],
            incarnation=thread["incarnation"],
            run_id=task.get("run_id") or "mcp-task:" + notification["task_id"],
            operation="native_notification",
            arguments=notification,
        )
        try:
            return await self.request("notification", source_run_id=task.get("run_id"), notification=notification, capability=capability)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in {403, 410}:
                raise PermanentNotificationError("Native notification capability or dependency rejected") from exc
            if exc.response.status_code == 409:
                raise ConflictError("Native dependencies are not ready") from exc
            raise

    async def admit(self, record):
        raise RuntimeError("Native worker accepts signed existing admissions only")

    async def request(self, operation, **args):
        response = await self.client.post(
            f"{self.config['executor_url'].rstrip('/')}/api/native-workers/{self.config['node_id']}/{operation}",
            json={"schema_revision": SCHEMA_REVISION, "protocol": PROTOCOL, "worker_version": WORKER_VERSION, "mount_id": self.mount_id, "owner": self.owner, **args},
        )
        response.raise_for_status()
        payload = response.json()
        if operation in {"bootstrap", "poll"} and payload.get("schema_revision") != SCHEMA_REVISION:
            raise RuntimeError("Executor schema capability mismatch")
        return payload

    async def report(self, job, changes):
        current = await self.request("get", job_id=job["id"], generation=job["generation"])
        if all(current.get(key) == value for key, value in changes.items()):
            return current
        return await self.request("report", job_id=job["id"], generation=job["generation"], expected=current, changes=changes)

    async def report_until_acknowledged(self, job, changes):
        while not getattr(self, "closing", False):
            try:
                return await self.report(job, changes)
            except (httpx.HTTPError, RuntimeError):
                await asyncio.sleep(1)
        raise asyncio.CancelledError

    async def stop_native(self, job):
        # Cancellation polling and the native task finalizer share one owned
        # physical stop. Failed/unknown proofs are retryable, never successes.
        task = self.stop_tasks.get(job["id"])
        if task is None:
            task = asyncio.create_task(asyncio.to_thread(stop_native_sandbox, job["native"]))
            self.stop_tasks[job["id"]] = task
        try:
            await asyncio.shield(task)
        except Exception:
            if self.stop_tasks.get(job["id"]) is task:
                self.stop_tasks.pop(job["id"], None)
            # Backend lifecycle failures include TimeoutExpired and OSError.
            # Normalize unknown STOP outcomes for the retained retry owner,
            # without catching cancellation/shutdown BaseExceptions.
            raise RuntimeError("Native physical STOP remains unconfirmed; retry required") from None

    async def stop_owned(self, job):
        from app.gateway.internal_auth import get_internal_user
        from deerflow.runtime.user_context import reset_current_user, set_current_user

        token = set_current_user(get_internal_user(job["native"]["user_id"]))
        try:
            await self.stop_native(job)
        finally:
            reset_current_user(token)

    async def drain_cancellations(self):
        while not getattr(self, "closing", False):
            for job, record in list(self.executions.values()):
                if not record.ownership_lost and (record.abort_event.is_set() or record.status.value == "interrupted"):
                    try:
                        await self.stop_owned(job)
                    except RuntimeError:
                        # Same owned STOP can retry; no claims or graph replay.
                        pass
            await asyncio.sleep(0.2)

    def check_admission(self):
        if getattr(self, "quiescing", False) or getattr(self, "closing", False):
            raise RuntimeError("Native worker is quiescing")

    async def adopt_owned(self, job, token):
        from app.gateway.native_admission import adopt_native_run

        async with self.adoption_lock:
            self.check_admission()
            self.adopting = asyncio.current_task()
            try:
                browser = getattr(self, "browser_control", None)
                if browser is not None:
                    # Verify the launch before its identity may bind browser
                    # state; adoption itself verifies it again at the native fence.
                    native = verify_native_launch(job, token, self.secret)
                    with await browser.execution_scope(native) as attach_browser_task:
                        record = await adopt_native_run(self.app, job, token, self.secret, admission_check=self.check_admission)
                        attach_browser_task(record.task)
                        return record
                return await adopt_native_run(self.app, job, token, self.secret, admission_check=self.check_admission)
            finally:
                self.adopting = None

    async def quiesce(self):
        self.quiescing = True
        if self.task is not None:
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task
        try:
            await asyncio.wait_for(self.adoption_lock.acquire(), timeout=5)
        except TimeoutError:
            if self.adopting is not None:
                self.adopting.cancel()
                await asyncio.wait([self.adopting], timeout=1)
        else:
            self.adoption_lock.release()
        if getattr(self, "cleanup_task", None) is None:
            self.cleanup_task = asyncio.create_task(self.drain_cancellations())
        # The synchronous attach check remains fenced even if an old database
        # operation takes longer to unwind than this bounded barrier.

    async def execute(self, job, token):

        try:
            verify_native_launch(job, token, self.secret)
            budget = job["node_budget"]
            if budget["max_concurrency"] != 1 or budget["resident_cpu_millis"] < 1500 or budget["resident_memory_mib"] < 2048 or job["node_id"] != self.config["node_id"]:
                raise ValueError("Native worker resident budget mismatch")
            job = await self.report_until_acknowledged(job, {"start_intent": True})
            record = await self.adopt_owned(job, token)
            self.executions[job["id"]] = (job, record)
            await self.report_until_acknowledged(job, {"state": "running", "started_at": time.time()})
            await asyncio.shield(record.task)
            if record.ownership_lost:
                raise RuntimeError("Native task ownership was lost; physical outcome requires reconciliation")
            # AIO container remains within the continuously charged resident
            # budget. The native task has fully drained its finalizers here.
            while not getattr(self, "closing", False):
                try:
                    latest = await self.request("get", job_id=job["id"], generation=job["generation"])
                    state = "cancelled" if latest.get("cancel_requested") or record.status.value == "interrupted" else {"success": "completed"}.get(record.status.value, "failed")
                    if state == "cancelled":
                        await self.stop_owned(job)
                    await self.report(job, {"state": state, "error": record.error, "physical_stopped": True, "physical_stopped_at": time.time()})
                    break
                except (httpx.HTTPError, RuntimeError):
                    # Retry this settled native outcome/owned STOP, never the
                    # graph. Polling retains cancellation access meanwhile.
                    await asyncio.sleep(1)
        except Exception:
            native = job["native"]
            row = await self.app.state.run_store.get(native["run_id"], user_id=native["user_id"])
            if row is not None and row.get("owner_worker_id") == "dispatch:" + job["id"] and row["status"] == "pending":
                while not getattr(self, "closing", False):
                    try:
                        await self.request("refuse", job_id=job["id"], generation=job["generation"])
                        return
                    except (httpx.HTTPError, RuntimeError):
                        await asyncio.sleep(1)
            logger.exception("Native worker attempt requires reconciliation")
            # Unknown attempts retain their reservation; never replay execution.
            with suppress(Exception):
                await self.report(job, {"state": "uncertain", "error": "Native worker attempt outcome requires reconciliation"})
        finally:
            self.active.pop(job["id"], None)
            self.executions.pop(job["id"], None)
            stop = self.stop_tasks.get(job["id"])
            if stop is not None and stop.done():
                self.stop_tasks.pop(job["id"], None)

    async def run(self):
        while True:
            try:
                response = await self.request("poll")
                envelopes = response["owned"] + ([response["claim"]] if response["claim"] else [])
                seen = set()
                for envelope in envelopes:
                    job = envelope["job"]
                    if job["id"] in seen:
                        continue
                    seen.add(job["id"])
                    if job.get("cancel_requested"):
                        native = job["native"]
                        from app.gateway.internal_auth import get_internal_user
                        from deerflow.runtime.user_context import reset_current_user, set_current_user

                        token = set_current_user(get_internal_user(native["user_id"]))
                        try:
                            await self.app.state.run_manager.cancel(native["run_id"])
                            if job["id"] in self.active:
                                await self.stop_native(job)
                        finally:
                            reset_current_user(token)
                    if job["id"] not in self.active and job["state"] == "starting" and not job.get("start_intent"):
                        self.active[job["id"]] = asyncio.create_task(self.execute(job, envelope["capability"]))
                    elif job["id"] not in self.active and job.get("start_intent"):
                        # Restart cannot replay a started graph. Native leases
                        # reconcile the run; physical resources stay reserved.
                        await self.report(job, {"state": "uncertain"})
            except Exception:
                logger.exception("Native outbound worker poll failed")
            await asyncio.sleep(1)

    async def start(self):
        self.task = asyncio.create_task(self.run())

    async def stop(self):
        await self.quiesce()
        deadline = asyncio.get_running_loop().time() + 120
        native_tasks = [record.task for _, record in self.executions.values() if record.task is not None]
        if native_tasks:
            await asyncio.wait(native_tasks, timeout=max(0, deadline - asyncio.get_running_loop().time()))
        stops = list(self.stop_tasks.values())
        if stops:
            await asyncio.wait(stops, timeout=max(0, deadline - asyncio.get_running_loop().time()))
        self.closing = True
        if self.cleanup_task is not None:
            self.cleanup_task.cancel()
            with suppress(asyncio.CancelledError):
                await self.cleanup_task
        wrappers = list(self.active.values())
        for task in wrappers:
            task.cancel()
        if wrappers:
            await asyncio.wait(wrappers, timeout=1)
        # No claims, adopts or retry loop survives teardown. Native execution
        # and shielded physical STOP retain the client/lock quarantine until
        # their finalizers unwind, even beyond the bounded shutdown allowance.
        waiting = native_tasks + stops + wrappers

        async def release():
            browser = getattr(self, "browser_control", None)
            if browser is not None:
                # Native finalizers have drained. Physical browser uncertainty
                # retains this worker's node lock until process/container STOP.
                await browser.stop()
            await self.client.aclose()
            self.node_lock.close()

        if all(task.done() for task in waiting):
            await release()
        else:
            released = False

            def release_after_drain(_task):
                nonlocal released
                if not released and all(task.done() for task in waiting):
                    released = True
                    asyncio.create_task(release())

            for task in waiting:
                if not task.done():
                    task.add_done_callback(release_after_drain)


def stop_native_sandbox(native):
    """Destroy the exact native sandbox, and prove physical STOP before release."""
    from deerflow.sandbox.sandbox_provider import get_initialized_sandbox_provider

    provider = get_initialized_sandbox_provider()
    if provider is None:
        raise RuntimeError("Native sandbox physical STOP remains unconfirmed: provider unavailable")
    sandbox_id = provider._sandbox_id_for_thread(native["thread_id"], native["user_id"])
    provider.destroy(sandbox_id)
    backend = provider._backend
    name = backend._container_prefix + "-" + sandbox_id
    if backend._is_container_running(name):
        raise RuntimeError("Native sandbox physical STOP remains unconfirmed")
