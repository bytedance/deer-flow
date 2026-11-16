"""Versioned bridge journal replay; authority is reacquired from a live session.

SQLite retains its exclusive store owner. PostgreSQL uses a shared execution
lease and fenced admission; both replay the same committed bridge journal.
"""

import asyncio
import copy
import json

from deerflow_extension_api.plugins import ToolContext

RECOVERY_VERSION = 1


class Recovery:
    async def recover(self, payload, context):
        if set(payload) != {"run_id"}:
            raise ValueError("Recovery requires run_id")
        if isinstance(context, ToolContext) or context.interaction != "session" or context.principal.is_internal or context.agent_runs is None:
            raise ValueError("Recovery requires an authenticated browser session")
        task = asyncio.create_task(self.restore(payload, context))
        self.admissions.add(task)
        task.add_done_callback(self.admission_finished)
        return await asyncio.shield(task)

    async def restore(self, payload, context):
        from .service import identity, text

        async with self.launch_lock:
            owner = self.owner(context)
            run_id = text(payload["run_id"], 64)
            record = await asyncio.to_thread(self.store.get, owner, run_id)
            if run_id in self.entries:
                return {"run_id": run_id, "status": record["status"]}
            if record["status"] != "recoverable" or record.get("recovery_version") != RECOVERY_VERSION:
                raise ValueError("Workflow is not recoverable; inspect retained child outcomes")
            if record.get("runtime_version") != self.runtime_version:
                raise ValueError("Workflow runtime version changed; recovery requires the original compatible runtime")
            if record["script_hash"] != self.script_version(record["script"])[1] or record["args_hash"] != identity(record["args"]):
                raise ValueError("Recovery script or arguments changed")
            if len(self.entries) >= self.config["max_workflows"] or sum(e["owner"] == owner for e in self.entries.values()) >= self.config["max_workflows_per_owner"]:
                raise ValueError("Active workflow limit")
            entry = self.new_entry(owner, record, context.agent_runs)
            await self.check_configuration(entry)
            if self.clustered:
                record = await asyncio.to_thread(self.store.claim, owner, run_id)
                entry = self.new_entry(owner, record, context.agent_runs)
            # A committed admission intent with no receipt is never dispatched
            # again. An operator must reconcile its external effects first.
            uncertain = [s for s in record["steps"] if s["status"] not in ("queued", "completed", "running") or (s["status"] == "running" and not s.get("run_id"))]
            if uncertain:
                record.update(
                    status="needs_reconciliation",
                    error="Uncertain child admission or outcome; inspect child identities before retrying",
                )
                await self.save(owner, record)
                return {"run_id": run_id, "status": record["status"]}
            for artifact in record.get("artifacts", []):
                await asyncio.to_thread(self.store.artifact, owner, run_id, artifact["version"])
            entry["replay"] = copy.deepcopy(record["journal"])
            record.update(status="queued", error=None)
            await self.save(owner, record)
            self.publish(entry)
            return {"run_id": run_id, "status": "queued"}

    async def begin_frame(self, entry, frame):
        """Persist intent before effects; replay verifies every emitted request."""
        record = entry["record"]
        replay = entry.get("replay", [])
        index = entry.setdefault("frame_index", 0)
        entry["frame_index"] = index + 1
        entry["recover_frame"] = False
        if index < len(replay):
            expected = replay[index]
            if expected["frame"] != frame:
                raise ValueError("Recovery diverged from committed bridge history")
            pending = entry.setdefault("replay_pending", {})
            for message in frame["messages"]:
                if message.get("type") == "agent":
                    pending[message["id"]] = message
            if expected["responses"] is not None:
                for response in expected["responses"]:
                    pending.pop(response["id"], None)
                return expected["responses"]
            entry["recover_frame"] = True
        else:
            item = {"frame": copy.deepcopy(frame), "responses": None}
            size = len(json.dumps(item).encode())
            if record.get("journal_bytes", 0) + size > 4 * 1024 * 1024:
                raise ValueError("Recovery journal limit (4 MiB)")
            record["journal_bytes"] = record.get("journal_bytes", 0) + size
            record["journal"].append(item)
            await self.save(entry["owner"], record)
        # Restore requests outstanding across earlier response batches too.
        pending = entry.pop("replay_pending", {})
        current = {m.get("id") for m in frame["messages"]}
        for message in pending.values():
            if message["id"] not in current:
                entry["tasks"].add(asyncio.create_task(self.step(entry, message, replay=True)))
        return None

    async def deliver_frame(self, entry, process, responses):
        record = entry["record"]
        record["remaining_seconds"] = max(0, entry["deadline"].when() - asyncio.get_running_loop().time())
        size = len(json.dumps(responses).encode())
        if record.get("journal_bytes", 0) + size > 4 * 1024 * 1024:
            raise ValueError("Recovery journal limit (4 MiB)")
        record["journal_bytes"] = record.get("journal_bytes", 0) + size
        record["journal"][entry["frame_index"] - 1]["responses"] = copy.deepcopy(responses)
        await self.save(entry["owner"], record)
        await self.send(process, {"responses": responses})
