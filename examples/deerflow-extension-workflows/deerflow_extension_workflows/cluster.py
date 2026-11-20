"""Leased execution and durable cross-Gateway controls, without stored authority."""

import asyncio
import copy
from contextlib import asynccontextmanager

from deerflow_extension_api import ExecutionFence

from .constants import NAMESPACE


class Cluster:
    @staticmethod
    def slot_releasable(row):
        return (
            (row.get("admission_rejected") is True and row.get("run_id") is None)
            or row["status"] in ("completed", "cancelled", "waiting_input")
            or row.get("child_status") in ("success", "error", "interrupted", "timeout")
        )

    def dispatch_fence(self, record):
        if not self.clustered:
            return {}
        return {"execution_fence": ExecutionFence(NAMESPACE, record["id"], self.holder_id, record["execution_epoch"])}

    @asynccontextmanager
    async def cluster_slot(self, entry, row):
        if not self.clustered:
            yield
            return
        record, owner = entry["record"], entry["owner"]
        while not await asyncio.to_thread(self.store.reserve_slot, owner, record, row["step_id"]):
            if entry["cancel"].is_set():
                raise ValueError("Workflow stopping")
            await asyncio.sleep(0.1)
        try:
            yield
        finally:
            # Unknown admission/outcome retains its cluster reservation. Losing
            # an execution lease must never make a possibly live child free.
            if self.slot_releasable(row) and not entry.get("lease_lost"):
                await asyncio.to_thread(self.store.release_slot, owner, record, row["step_id"])

    async def follow_lease(self, entry):
        record, owner = entry["record"], entry["owner"]
        try:
            while record["id"] in self.entries:
                async with self.write_lock:
                    commands = await asyncio.to_thread(self.store.heartbeat, owner, record)
                    changed, wake = False, False
                    for command in commands:
                        if command["kind"] == "cancel":
                            entry["cancel"].set()
                            entry["suspending"] = False
                            continue
                        row = next((r for r in record["checkpoints"] if r["step_id"] == command["step_id"]), None)
                        if row and row["status"] == "pending":
                            if row["attempt"] != command["attempt"] or row.get("artifact_version") != command["artifact_version"]:
                                raise ValueError("Committed checkpoint identity changed")
                            row.update(status=command["status"], decided_by=owner, decided_at=command["decided_at"])
                            changed, wake = True, True
                    if changed:
                        record["revision"] = await asyncio.to_thread(self.store.put, owner, copy.deepcopy(record))
                    if wake and entry.get("gate"):
                        entry["gate"].set()
                await asyncio.sleep(min(1, self.config["lease_seconds"] / 3))
        except asyncio.CancelledError:
            raise
        except Exception:
            # Fail closed on loss of contact too. The durable epoch, checked by
            # every write and host admission, is the authority, not this signal.
            entry["lease_lost"] = True
            entry["fault"] = "Workflow execution lease lost"
            entry["cancel"].set()
            process = self.processes.get(record["id"])
            if process and process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass

    async def remote_command(self, owner, record, context, command):
        entry = self.new_entry(owner, record, context.agent_runs)
        await self.check_configuration(entry)
        key = "cancel" if command["kind"] == "cancel" else command["step_id"]
        await asyncio.to_thread(self.store.command, owner, record["id"], key, command, record.get("revision", 0))

    async def cancel_recovered(self, owner, run_id, context):
        record = await asyncio.to_thread(self.store.get, owner, run_id)
        await self.check_configuration(self.new_entry(owner, record, context.agent_runs))
        record = await asyncio.to_thread(self.store.claim, owner, run_id, for_cancel=True)
        entry = self.new_entry(owner, record, context.agent_runs)
        record["status"] = "cancelling"
        await self.save(owner, record)
        self.entries[run_id] = entry
        guardian = asyncio.create_task(self.follow_lease(entry))
        try:
            for row in record["steps"]:
                if entry.get("lease_lost"):
                    raise ValueError("Workflow execution lease lost")
                if row.get("run_id") and row["status"] != "completed":
                    await self.cancel_child(context.agent_runs, row, record=record)
                if self.slot_releasable(row):
                    await asyncio.to_thread(self.store.release_slot, owner, record, row["step_id"])
            uncertain = any(r["status"] not in ("completed", "queued", "cancelled") for r in record["steps"])
            record.update(status="needs_reconciliation" if uncertain else "cancelled", error="Inspect uncertain child effects" if uncertain else None)
            await self.save(owner, record)
            return {"run_id": run_id, "status": record["status"]}
        finally:
            guardian.cancel()
            await asyncio.gather(guardian, return_exceptions=True)
            self.entries.pop(run_id, None)
