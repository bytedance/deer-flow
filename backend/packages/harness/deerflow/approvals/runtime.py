"""Host-owned bridge from isolated child loops to the Run's approval store."""

from __future__ import annotations

import asyncio
import copy
import time
from uuid import uuid4

from deerflow.approvals.store import ApprovalConflict


class ApprovalRuntime:
    def __init__(self, store, *, scope, run_id, mode, timeout, record, journal=None, interactive=True):
        self.store = store
        self.scope = scope
        self.run_id = run_id
        self.mode = mode
        self.timeout = timeout
        self.record = record
        self.journal = journal
        self.loop = asyncio.get_running_loop()
        self.user_messages = []
        self.closed = False
        self.interactive = interactive

    def set_user_messages(self, messages):
        self.user_messages = list(messages)

    def child(self):
        # No RunJournal/SQL handle is exposed to the isolated loop. Even user
        # intent is copied at delegation, rather than mutated by child prompts.
        return ApprovalRuntimeProxy(self, self.mode, tuple(self.user_messages))

    def _check_active(self):
        if self.closed or self.record.ownership_lost or self.record.abort_event.is_set():
            raise ApprovalConflict("The originating run is no longer active")

    async def has_grant(self, fingerprint):
        self._check_active()
        return await self.store.has_grant(fingerprint, scope=self.scope)

    def _row(self, plan, *, kind, payload):
        return {
            "request_id": plan["request_id"],
            "user_id": self.scope[0],
            "thread_id": self.scope[1],
            "incarnation": self.scope[2],
            "run_id": self.run_id,
            "fingerprint": plan["fingerprint"],
            "kind": kind,
            "status": "pending",
            "decision": None,
            "payload": copy.deepcopy(payload),
            "response": None,
            "created_at": time.time(),
            "expires_at": time.time() + self.timeout if kind == "live" else None,
        }

    async def wait_for_decision(self, plan, payload):
        self._check_active()
        payload = {**payload, "transport": "live", "run_id": self.run_id}
        row = self._row(plan, kind="live", payload=payload)
        payload["expires_at"] = row["expires_at"]
        row["payload"] = payload
        await self.store.create(row)
        try:
            async with asyncio.timeout(self.timeout):
                while True:
                    self._check_active()
                    current = await self.store.get(plan["request_id"], scope=self.scope)
                    if current is None or current["status"] not in ("pending", "decided"):
                        raise ApprovalConflict("Approval was cancelled or expired")
                    if current["status"] == "decided":
                        return current["response"]
                    await asyncio.sleep(0.25)
        except (TimeoutError, ApprovalConflict):
            return {"responses": [{"request_id": plan["request_id"], "tool_call_id": plan["tool_call_id"], "option_id": "reject"}]}
        except asyncio.CancelledError:
            from deerflow.utils.file_io import await_drained

            await await_drained(self.store.cancel_request(plan["request_id"], scope=self.scope))
            raise

    async def record_decision(self, plan, decision, *, arguments=None):
        self._check_active()
        # Automatic outcomes retain only identifiers and assessment. Human
        # reviews retain the exact proposal, needed for inspecting/revoking a
        # thread grant. These records remain owner-scoped and thread-deletable.
        payload = {key: plan[key] for key in ("tool_name", "mode", "reason")}
        if "review" in plan:
            payload["review"] = copy.deepcopy(plan["review"])
        if decision in ("approve", "approve_thread", "edit", "reject"):
            payload.update(arguments=arguments if arguments is not None else plan["args"], source=plan["descriptor"]["source"])
        row = await self.store.get(plan["request_id"], scope=self.scope)
        if row is None:
            await self.store.create(self._row(plan, kind="audit", payload=payload))
        await self.store.finish(plan["request_id"], scope=self.scope, decision=decision)
        if self.journal is not None:
            self.journal.record_middleware(
                "tool_approval", name="ToolApprovalMiddleware", hook="wrap_tool_call", action=decision, changes={"request_id": plan["request_id"], "tool_call_id": plan["tool_call_id"], "tool_name": plan["tool_name"], "mode": plan["mode"]}
            )

    async def record_usage(self, response, model_name):
        if self.journal is None:
            return
        usage = getattr(response, "usage_metadata", None) or {}

        def tokens(key):
            value = usage.get(key)
            return value if type(value) is int and value >= 0 else 0

        input_tokens, output_tokens = tokens("input_tokens"), tokens("output_tokens")
        metadata = getattr(response, "response_metadata", None) or {}
        self.journal.record_external_llm_usage_records(
            [
                {
                    "source_run_id": f"tool-approval:{uuid4().hex}",
                    "caller": "middleware:tool_approval",
                    "model_name": metadata.get("model_name") or metadata.get("model") or model_name,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "total_tokens": tokens("total_tokens") or input_tokens + output_tokens,
                    "count_call": 1,
                    "usage_missing": int(not usage),
                }
            ]
        )

    async def close(self):
        self.closed = True
        try:
            await self.store.cancel_run(self.run_id, scope=self.scope)
        finally:
            self.journal = None
            self.user_messages = []


class ApprovalRuntimeProxy:
    def __init__(self, parent, mode, user_messages):
        self._parent = parent
        self.mode = mode
        self.user_messages = list(user_messages)
        self.interactive = parent.interactive

    async def _call(self, method, *args, **kwargs):
        parent = self._parent
        if parent.closed or parent.loop.is_closed():
            raise ApprovalConflict("The parent approval channel is closed")
        coroutine = getattr(parent, method)(*args, **kwargs)
        if asyncio.get_running_loop() is parent.loop:
            return await coroutine
        try:
            future = asyncio.run_coroutine_threadsafe(coroutine, parent.loop)
        except BaseException:
            coroutine.close()
            raise
        return await asyncio.wrap_future(future)

    async def has_grant(self, fingerprint):
        return await self._call("has_grant", fingerprint)

    async def wait_for_decision(self, plan, payload):
        return await self._call("wait_for_decision", plan, payload)

    async def record_decision(self, plan, decision, *, arguments=None):
        return await self._call("record_decision", plan, decision, arguments=arguments)

    async def record_usage(self, response, model_name):
        # Snapshot only normalized usage before crossing the loop boundary.
        from types import SimpleNamespace

        snapshot = SimpleNamespace(usage_metadata=copy.deepcopy(getattr(response, "usage_metadata", None)), response_metadata=copy.deepcopy(getattr(response, "response_metadata", None)))
        return await self._call("record_usage", snapshot, model_name)
