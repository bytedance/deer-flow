"""Concurrent answers, restart reads and thread grants use the real SQL store."""

import asyncio
import time

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from deerflow.approvals.store import ApprovalConflict, ApprovalStore
from deerflow.persistence.tool_approvals.model import ToolApprovalRow


@pytest_asyncio.fixture(params=["memory", "sqlite"])
async def store(request, tmp_path):
    if request.param == "memory":
        yield ApprovalStore()
        return
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'approvals.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(lambda sync: ToolApprovalRow.__table__.create(sync))
    yield ApprovalStore(async_sessionmaker(engine, expire_on_commit=False))
    await engine.dispose()


SCOPE = ("owner", "thread", "incarnation")


def pending(request_id="request", **overrides):
    return {
        "request_id": request_id,
        "user_id": SCOPE[0],
        "thread_id": SCOPE[1],
        "incarnation": SCOPE[2],
        "run_id": "run",
        "fingerprint": "fingerprint",
        "kind": "live",
        "status": "pending",
        "decision": None,
        "payload": {},
        "response": None,
        "created_at": time.time(),
        "expires_at": time.time() + 60,
        **overrides,
    }


@pytest.mark.asyncio
async def test_concurrent_answers_accept_only_one_and_retry_is_idempotent(store):
    await store.create(pending())
    answers = [{"responses": [{"option_id": decision}]} for decision in ("approve", "reject")]
    results = await asyncio.gather(*(store.decide("request", answer, scope=SCOPE, fingerprint="fingerprint") for answer in answers), return_exceptions=True)
    assert sum(result is None for result in results) == 1
    assert sum(isinstance(result, ApprovalConflict) for result in results) == 1
    row = await store.get("request", scope=SCOPE)
    await store.decide("request", row["response"], scope=SCOPE, fingerprint="fingerprint")


@pytest.mark.asyncio
async def test_owner_incarnation_and_exact_operation_bound_grant_and_revocation(store):
    await store.create(pending())
    await store.finish("request", scope=SCOPE, decision="approve_thread")
    assert await store.has_grant("fingerprint", scope=SCOPE)
    assert not await store.has_grant("changed-args", scope=SCOPE)
    assert not await store.has_grant("fingerprint", scope=("other", *SCOPE[1:]))
    assert not await store.has_grant("fingerprint", scope=(*SCOPE[:2], "recreated"))
    if store.sf is not None:
        assert await ApprovalStore(store.sf).has_grant("fingerprint", scope=SCOPE)
    await store.revoke(scope=SCOPE)
    assert not await store.has_grant("fingerprint", scope=SCOPE)


@pytest.mark.asyncio
async def test_cancelled_or_expired_child_cannot_be_approved_or_granted(store):
    await store.create(pending())
    await store.create(pending("expired", expires_at=time.time() - 1))
    await store.cancel_run("run", scope=SCOPE)
    for request_id in ("request", "expired"):
        with pytest.raises(ApprovalConflict):
            await store.decide(request_id, {"responses": []}, scope=SCOPE, fingerprint="fingerprint")
        with pytest.raises(ApprovalConflict):
            await store.finish(request_id, scope=SCOPE, decision="approve_thread")
    await store.delete_thread("thread", user_id="owner")
    assert await store.list(scope=SCOPE) == []
