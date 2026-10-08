"""Standalone ordinary MCP server backed by an execution ledger and local Docker."""

from __future__ import annotations

import asyncio
import hmac
import json
import os
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import CallToolResult, TextContent
from starlette.responses import JSONResponse, Response

from ecs_executor.job_store import JobStore
from ecs_executor.jobs import ExecutionJobs, ExecutionProfile
from ecs_executor.scope import SCOPE_HEADER
from ecs_executor.worker import LocalWorker


def create_server(jobs: ExecutionJobs, *, user_credentials: dict[str, str], discovery_credential: str, artifact_base_url: str = "http://127.0.0.1:8003") -> FastMCP:
    credentials = list(user_credentials.values())
    if not discovery_credential or any(not token for token in credentials) or len(set(credentials + [discovery_credential])) != len(credentials) + 1:
        raise ValueError("Separate nonempty user and discovery credentials are required")
    server = FastMCP("DeerFlow local execution", stateless_http=True, json_response=True)

    def owner(headers):
        authorization = headers.get("authorization", "")
        for user_id, token in user_credentials.items():
            if hmac.compare_digest(authorization, "Bearer " + token):
                return user_id
        raise ValueError("Authenticated execution owner is required")

    async def call(operation, args, ctx):
        try:
            request = ctx.request_context.request
            user_id = owner(request.headers)
            result = await asyncio.to_thread(getattr(jobs, operation), user_id, request.headers.get(SCOPE_HEADER, ""), args)
            if "result_artifact" in result and result["result_artifact"]["uri"].startswith("/artifacts/"):
                result["result_artifact"]["uri"] = artifact_base_url.rstrip("/") + result["result_artifact"]["uri"]
            return CallToolResult(content=[TextContent(type="text", text=json.dumps(result))], structuredContent=result)
        except (ValueError, RuntimeError):
            # Error remains retryable to the native ordinary driver. No failure
            # claims or cancellation success until the physical outcome is known.
            return CallToolResult(isError=True, content=[TextContent(type="text", text="Execution request denied or physical operation pending; retry management calls")])

    @server.tool()
    async def submit(request_key: str, profile: str, argv: list[str], ctx: Context, input_files: dict[str, str] | None = None, input_refs: dict[str, dict[str, str]] | None = None) -> CallToolResult:
        """Stage an owner-authorized command in the execution queue."""
        args = {"request_key": request_key, "profile": profile, "argv": argv}
        if input_files is not None:
            args["input_files"] = input_files
        if input_refs is not None:
            args["input_refs"] = input_refs
        return await call("submit", args, ctx)

    @server.tool()
    async def status(task_id: str, ctx: Context) -> CallToolResult:
        """Read execution status and activate a durably tracked staged job."""
        return await call("status", {"task_id": task_id}, ctx)

    @server.tool()
    async def cancel(task_id: str, ctx: Context) -> CallToolResult:
        """Cancel a staged job or request and verify physical STOP."""
        return await call("cancel", {"task_id": task_id}, ctx)

    @server.custom_route("/artifacts/{job_id}", methods=["GET"])
    async def artifact(request):
        try:
            user_id = owner(request.headers)
            payload = await asyncio.to_thread(jobs.read_artifact, user_id, request.path_params["job_id"])
            return JSONResponse(payload, headers={"Cache-Control": "private, no-store"})
        except ValueError:
            return Response(status_code=404)
        except RuntimeError:
            return Response(status_code=409)

    # Discovery intentionally returns schemas only. Knowledge of this credential
    # never supplies a user identity to an execution or artifact operation.
    return server


def create_app(jobs: ExecutionJobs, **kwargs):
    """One worker process owns the local ledger/container namespace at a time."""
    import fcntl

    server = create_server(jobs, **kwargs)
    app = server.streamable_http_app()
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application):
        jobs.artifact_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        with (jobs.artifact_root / "worker.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            worker = LocalWorker(jobs)
            async with original_lifespan(application):
                task = asyncio.create_task(worker.run())
                try:
                    yield
                finally:
                    task.cancel()
                    with suppress(asyncio.CancelledError):
                        await task

    app.router.lifespan_context = lifespan
    return app


def main():
    """Operator configuration is a private JSON file, never model arguments."""
    import uvicorn

    path = os.environ.get("ECS_EXECUTOR_CONFIG")
    if not path:
        raise ValueError("ECS_EXECUTOR_CONFIG must name an operator configuration file")
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    store = JobStore(config["database_url"])
    store.initialize()
    jobs = ExecutionJobs(
        store,
        secret=os.environ["ECS_EXECUTOR_SCOPE_SECRET"].encode(),
        audience=config["audience"],
        profiles={name: ExecutionProfile.model_validate(profile) for name, profile in config["profiles"].items()},
        user_profiles={user: set(profiles) for user, profiles in config["user_profiles"].items()},
        artifact_root=Path(config["artifact_root"]),
        allowed_networks=set(config.get("allowed_networks", ["none"])),
        workspace_root=Path(config["workspace_root"]) if config.get("workspace_root") else None,
        metadata_database_url=config.get("metadata_database_url"),
        max_input_bytes=config.get("max_input_bytes", 8 * 1024 * 1024),
    )
    app = create_app(
        jobs, user_credentials={user: os.environ[variable] for user, variable in config["user_credential_env"].items()}, discovery_credential=os.environ[config["discovery_credential_env"]], artifact_base_url=config["artifact_base_url"]
    )
    uvicorn.run(app, host="127.0.0.1", port=config.get("port", 8003))


if __name__ == "__main__":
    main()
