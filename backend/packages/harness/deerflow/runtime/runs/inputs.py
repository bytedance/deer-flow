"""Bounded, durable inputs belonging to one admitted Run.

The run store serializes mutations with status/cancellation. Only the owning
worker may acknowledge graph input; HTTP acceptance never writes a checkpoint.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Literal
from uuid import NAMESPACE_URL, uuid5

from deerflow.utils.time import now_iso

MAX_INPUTS = 16
MAX_INPUT_BYTES = 16 * 1024
MAX_TOTAL_BYTES = 64 * 1024
INPUT_CONTEXT_KEY = "__run_input_control"


class InputConflict(ValueError):
    """The target Run cannot accept or apply this input."""


class InputCancelled(InputConflict):
    """The atomic dispatch claim found an explicitly cancelled input."""


def empty_input_state() -> dict[str, Any]:
    return {"closed": False, "items": []}


@dataclass
class RunInputs:
    store: Any
    run_id: str
    user_id: str | None
    worker_id: str | None = None

    async def read(self) -> dict[str, Any]:
        row = await self.store.get(self.run_id, user_id=self.user_id)
        if row is None:
            raise InputConflict("Run not found")
        return copy.deepcopy(row.get("run_inputs") or empty_input_state())

    async def _change(self, change, *, owned=False):
        if owned and self.worker_id is None:
            raise InputConflict("Run input application requires its owning worker")
        return await self.store.mutate_run_inputs(self.run_id, change, user_id=self.user_id, owner_worker_id=self.worker_id if owned else None)

    async def submit(
        self,
        request_id: str,
        text: str,
        mode: Literal["queue", "steer"],
        *,
        context: dict | None = None,
        source: Literal["user", "extension"] = "user",
        attachment_stage: dict | None = None,
    ) -> dict:
        if attachment_stage and mode != "queue":
            raise InputConflict("Attachments require queue mode")
        if not isinstance(text, str) or (not text.strip() and not attachment_stage) or len(text.encode("utf-8")) > MAX_INPUT_BYTES:
            raise InputConflict("Input must contain text of at most 16 KiB")
        if mode not in ("queue", "steer") or not isinstance(request_id, str) or not 1 <= len(request_id) <= 96:
            raise InputConflict("Invalid input mode or request ID")
        context = copy.deepcopy(context or {}) if mode == "queue" else {}

        def change(state, row):
            old = next((x for x in state["items"] if x["id"] == request_id), None)
            if old is not None:
                if (old["text"], old["mode"], old.get("context", {}), old.get("source", "user")) != (text, mode, context, source):
                    raise InputConflict("Request ID already belongs to different input")
                if (old.get("attachment_stage") or {}).get("files") != (attachment_stage or {}).get("files"):
                    raise InputConflict("Request ID already belongs to different attachments")
                return
            if state["closed"] or row.get("status") not in ("pending", "running") or row.get("operation_kind", "run") != "run" or row.get("cancel_action"):
                raise InputConflict("Run is finishing or stopped; this input was not accepted")
            if attachment_stage and state.get("queue_attachments") is not True:
                raise InputConflict("This Run cannot dispatch queued attachments")
            if len(state["items"]) >= MAX_INPUTS or sum(len(x["text"].encode("utf-8")) for x in state["items"]) + len(text.encode("utf-8")) > MAX_TOTAL_BYTES:
                raise InputConflict("Too many inputs for this Run; wait for it to finish")
            item = {"id": request_id, "text": text, "mode": mode, "context": context, "source": source, "status": "pending", "message_id": str(uuid5(NAMESPACE_URL, f"deerflow-input:{self.run_id}:{request_id}")), "created_at": now_iso()}
            if attachment_stage:
                item["attachment_stage"] = attachment_stage
            state["items"].append(item)

        state = await self._change(change)
        return next(x for x in state["items"] if x["id"] == request_id)

    async def acknowledge(self, ids: list[str]) -> None:
        def change(state, row):
            for item in state["items"]:
                if item["id"] in ids and item["mode"] == "steer" and item["status"] == "applying":
                    item["status"] = "applied"

        await self._change(change, owned=True)

    async def claim_steer(self, ids: list[str]) -> list[dict]:
        def change(state, row):
            if row.get("status") not in ("pending", "running") or row.get("cancel_action"):
                raise InputConflict("Run stopped before applying input")
            for item in state["items"]:
                if item["id"] in ids and item["mode"] == "steer" and item["status"] == "pending":
                    item["status"] = "applying"

        state = await self._change(change, owned=True)
        return [x for x in state["items"] if x["id"] in ids and x["mode"] == "steer" and x["status"] == "applying"]

    async def close(self, delivered: set[str] | None = None) -> bool:
        def change(state, row):
            if not any(x["mode"] == "steer" and x["status"] in ("pending", "applying") and x["id"] not in (delivered or set()) for x in state["items"]):
                state["closed"] = True

        return (await self._change(change, owned=True))["closed"]

    async def reopen(self) -> None:
        def change(state, row):
            if row.get("status") in ("pending", "running") and not row.get("cancel_action"):
                state["closed"] = False
                # Only the owning worker enables this. An older Gateway in a
                # rolling upgrade would otherwise dispatch the text alone.
                state["queue_attachments"] = True

        await self._change(change, owned=True)

    async def pause(self) -> None:
        def change(state, row):
            state["closed"] = True
            for item in state["items"]:
                if item["status"] in ("pending", "applying"):
                    item["status"] = "not_applied"

        await self._change(change)

    async def dispatched(self, input_id: str, run_id: str, *, attempt: int = 0) -> None:
        def change(state, row):
            item = next(x for x in state["items"] if x["id"] == input_id)
            # The worker can fail publication before admission returns its
            # receipt. A late receipt must not hide the retryable item.
            if item.get("attachment_attempt", 0) != attempt:
                return
            if item.get("run_id") not in (None, run_id):
                raise InputConflict("Queued input already belongs to another Run")
            item["run_id"] = run_id
            stage = item.get("attachment_stage")
            # Keep polling admitted attachments until the worker publishes them.
            if not stage or stage.get("published") is True:
                item["status"] = "applied"

        await self._change(change)

    async def begin_attachment_publication(self, input_id: str, run_id: str, *, attempt: int) -> None:
        def change(state, row):
            item = next(x for x in state["items"] if x["id"] == input_id)
            stage = item.get("attachment_stage")
            if not stage or stage.get("published") is True or item["status"] not in ("dispatching", "applied"):
                raise InputConflict("Queued attachment is no longer dispatching")
            if item.get("attachment_attempt", 0) != attempt or item.get("run_id") not in (None, run_id) or stage.get("publishing_attempt") == attempt:
                raise InputConflict("Queued attachment dispatch changed")
            stage["publishing_attempt"] = attempt

        await self._change(change)

    async def publication_failed(self, input_id: str, run_id: str, *, attempt: int, require_unstarted: bool = False) -> dict:
        def change(state, row):
            item = next(x for x in state["items"] if x["id"] == input_id)
            stage = item.get("attachment_stage")
            if not stage or stage.get("published") is True or item["status"] not in ("dispatching", "applied"):
                return
            if item.get("attachment_attempt", 0) != attempt or item.get("run_id") not in (None, run_id):
                return
            if require_unstarted and stage.get("publishing_attempt") == attempt:
                return
            item.pop("run_id", None)
            item.update(status="not_applied", attachment_attempt=attempt + 1)

        state = await self._change(change)
        return next(x for x in state["items"] if x["id"] == input_id)

    async def publication_succeeded(self, input_id: str, run_id: str, *, attempt: int) -> None:
        def change(state, row):
            item = next(x for x in state["items"] if x["id"] == input_id)
            stage = item.get("attachment_stage")
            if stage and item["status"] in ("dispatching", "applied") and item.get("attachment_attempt", 0) == attempt and item.get("run_id") in (None, run_id):
                stage["published"] = True
                if item.get("run_id") == run_id:
                    item["status"] = "applied"

        await self._change(change)

    async def claim(self, input_id: str, *, retry=False) -> dict:
        def change(state, row):
            if row.get("status") in ("pending", "running"):
                raise InputConflict("The current Run has not finished")
            item = next((x for x in state["items"] if x["id"] == input_id), None)
            if item is None:
                raise InputConflict("Input not found or removed")
            if item["status"] == "cancelled":
                raise InputCancelled("This input was cancelled")
            if item["status"] == "applied":
                if not item.get("run_id"):
                    raise InputConflict("This input was already applied")
                return
            if not retry and (row.get("status") != "success" or row.get("stop_reason") or item["mode"] != "queue" or item["status"] == "not_applied"):
                raise InputConflict("Queued input requires an explicit retry")
            item["status"] = "dispatching"

        state = await self._change(change)
        return next(x for x in state["items"] if x["id"] == input_id)

    async def cancel(self, input_id: str) -> dict:
        def change(state, row):
            item = next((x for x in state["items"] if x["id"] == input_id), None)
            if item is None or item["status"] not in ("pending", "not_applied", "cancelled"):
                raise InputConflict("This input is already being applied")
            item["status"] = "cancelled"

        state = await self._change(change)
        return next(x for x in state["items"] if x["id"] == input_id)
