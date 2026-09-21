"""Recovery is an authenticated host operation, never a plugin route."""

from dataclasses import dataclass
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, Request

from deerflow.skills.mutations.workers import MutationWorkers


@pytest.mark.asyncio
@pytest.mark.parametrize("role,source,status", [("user", None, 403), ("admin", "pat", 403), ("admin", None, 200)])
async def test_admin_recovery_auth_and_off_loop(role, source, status):
    import threading

    from app.gateway.routers.skill_mutations import router

    loop_thread = threading.get_ident()
    calls = []

    @dataclass
    class Result:
        operation_id: str
        publication: str = "APPLIED"

    class Recovery:
        def list_operations(self, *, limit, after_id):
            assert threading.get_ident() != loop_thread
            assert limit == 51 and after_id is None
            calls.append("list")
            return (Result("a" * 32),)

        def get_operation(self, operation_id):
            assert threading.get_ident() != loop_thread
            calls.append("query")
            return Result(operation_id)

        def recover_operation(self, operation_id):
            assert threading.get_ident() != loop_thread
            calls.append("recover")
            return Result(operation_id)

    app = FastAPI()
    workers = MutationWorkers()
    app.state.skill_mutation_host = SimpleNamespace(workers=workers, recovery=Recovery())

    @app.middleware("http")
    async def identity(request: Request, call_next):
        request.state.user = SimpleNamespace(id="admin", system_role=role)
        request.state.auth_source = source
        return await call_next(request)

    app.include_router(router)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            base = "/api/skill-mutations/operations/" + "a" * 32
            listed = await client.get("/api/skill-mutations/operations")
            assert listed.status_code == status
            if status == 200:
                assert listed.json()["items"][0]["operation_id"] == "a" * 32
            assert (await client.get(base)).status_code == status
            assert (await client.post(base + "/recover")).status_code == status
        assert calls == (["list", "query", "recover"] if status == 200 else [])
    finally:
        await workers.close()


@pytest.mark.asyncio
async def test_admin_errors_do_not_return_database_or_candidate_content():
    from deerflow_extension_api import HostCapabilityError

    from app.gateway.routers.skill_mutations import router

    class Recovery:
        def get_operation(self, operation_id):
            raise HostCapabilityError("NOT_FOUND_OR_FORBIDDEN", "candidate content must not leak")

    app = FastAPI()
    workers = MutationWorkers()
    app.state.skill_mutation_host = SimpleNamespace(workers=workers, recovery=Recovery())

    @app.middleware("http")
    async def identity(request: Request, call_next):
        request.state.user = SimpleNamespace(id="admin", system_role="admin")
        return await call_next(request)

    app.include_router(router)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/skill-mutations/operations/" + "a" * 32)
            assert response.status_code == 404
            assert "candidate content" not in response.text
    finally:
        await workers.close()
