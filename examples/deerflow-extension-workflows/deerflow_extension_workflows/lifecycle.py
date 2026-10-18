"""Immutable definitions and live-process checkpoints; never replay script effects."""

import asyncio
import copy
import re
import time

from deerflow_extension_api.plugins import ToolContext


class Lifecycle:
    async def save_definition(self, payload, context):
        from .service import text

        owner = self.owner(context)
        if set(payload) != {"name", "script"}:
            raise ValueError("Definition requires name and script")
        name = text(payload["name"], 80)
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", name):
            raise ValueError("Invalid definition name")
        script, version = self.script_version(payload["script"])
        return await asyncio.to_thread(self.store.save_definition, owner, name, version, script)

    @staticmethod
    def script_version(value):
        import hashlib

        from .service import encoded, text

        script = text(value, 16000)
        encoded(script, 16000)
        return script, hashlib.sha256(script.encode()).hexdigest()

    async def definitions(self, payload, context):
        return {"definitions": await asyncio.to_thread(self.store.definitions, self.owner(context))}

    async def get_definition(self, payload, context):
        from .service import text

        if set(payload) != {"name", "version"}:
            raise ValueError("Definition requires exact name and version")
        name, version = text(payload["name"], 80), text(payload["version"], 64)
        script = await asyncio.to_thread(self.store.definition, self.owner(context), name, version)
        return {"name": name, "version": version, "script": script}

    async def get_step(self, payload, context):
        from .service import encoded, text

        record = await asyncio.to_thread(self.store.get, self.owner(context), text(payload.get("run_id"), 64))
        row = next((s for s in record["steps"] if s["step_id"] == payload.get("step_id")), None)
        if row is None:
            row = next((s for s in record.get("artifacts", []) if s["step_id"] == payload.get("step_id")), None)
        if not row or row["status"] != "completed":
            raise ValueError("Completed step unavailable")
        result = {k: copy.deepcopy(v) for k, v in row.items() if k != "input"}
        encoded(result)
        return result

    async def check_configuration(self, entry):
        record = entry["record"]
        revision = record.get("configuration_revision")
        async with asyncio.timeout(5):
            current = await entry["runs"].configuration_revision(assistant_ids=sorted(self.config["agents"]))
        if revision is None or revision != current:
            raise ValueError("Agent configuration changed or unavailable; start a new workflow")
        from .service import identity

        if record["operator_revision"] != identity({**self.config, "agents": sorted(self.config["agents"])}):
            raise ValueError("Operator configuration changed; start a new workflow")

    async def checkpoint(self, entry, message, deadline):
        from .service import text

        record = entry["record"]
        payload = message.get("payload")
        human = message["type"] == "humanCheckpoint"
        keys = {"stepId", "sourceStepId", "artifactVersion"} if human else {"stepId"}
        if not isinstance(payload, dict) or set(payload) != keys:
            raise ValueError("Invalid checkpoint fields")
        step_id = text(payload["stepId"], 80)
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", step_id):
            raise ValueError("Invalid checkpoint stepId")
        if any(s["step_id"] == step_id for s in record["steps"] + record["checkpoints"] + record.get("artifacts", [])):
            raise ValueError("Step ID already used")
        if len(record["checkpoints"]) >= self.config["max_calls"]:
            raise ValueError("Checkpoint limit")
        await self.check_configuration(entry)
        row = {
            "step_id": step_id,
            "attempt": 1,
            "kind": message["type"],
            "status": "pending",
        }
        if human:
            source = next(
                (s for s in record["steps"] + record.get("artifacts", []) if s["step_id"] == payload["sourceStepId"] and s["status"] == "completed"),
                None,
            )
            if not source or source.get("artifact_version") != payload["artifactVersion"]:
                raise ValueError("Checkpoint must reference an exact retained step output version")
            row.update(
                artifact_kind=source.get("kind", "output"),
                source_step_id=source["step_id"],
                source_attempt=source["attempt"],
                artifact_version=source["artifact_version"],
            )
        entry["gate"] = asyncio.Event()
        record["checkpoints"].append(row)
        record["status"] = "waiting_approval" if human else "paused"
        record["pause_expires_at"] = time.time() + self.config["pause_timeout_seconds"]
        await self.save(entry["owner"], record)
        # Keep the same isolated worker/JS heap alive. No code before the gate is
        # replayed; suspend only the remaining execution wall budget while waiting.
        remaining = max(0, deadline.when() - asyncio.get_running_loop().time())
        deadline.reschedule(asyncio.get_running_loop().time() + self.config["pause_timeout_seconds"])
        signals = [
            asyncio.create_task(entry["gate"].wait()),
            asyncio.create_task(entry["cancel"].wait()),
        ]
        try:
            await asyncio.wait(signals, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for signal in signals:
                signal.cancel()
            await asyncio.gather(*signals, return_exceptions=True)
        if entry["cancel"].is_set() or row["status"] == "rejected":
            raise ValueError("Human rejected output" if row["status"] == "rejected" else "Cancelled")
        await self.check_configuration(entry)
        deadline.reschedule(asyncio.get_running_loop().time() + remaining)
        record["status"] = "running"
        record.pop("pause_expires_at", None)
        await self.save(entry["owner"], record)
        return {"id": message["id"], "value": {"status": row["status"]}}

    async def resume(self, payload, context):
        return await self.control(payload, context, human=False)

    async def decide(self, payload, context):
        return await self.control(payload, context, human=True)

    async def control(self, payload, context, *, human):
        # A cancelled HTTP request must not strand a persisted decision before
        # signalling the live worker. Service shutdown drains these tasks too.
        task = asyncio.create_task(self.apply_control(copy.deepcopy(dict(payload)), context, human=human))
        self.admissions.add(task)
        task.add_done_callback(self.admission_finished)
        return await asyncio.shield(task)

    async def apply_control(self, payload, context, *, human):
        from .service import text

        owner = self.owner(context)
        if context.agent_runs is None:
            raise ValueError("Session-bound AgentRuns required")
        if human and (context.interaction != "session" or isinstance(context, ToolContext) or context.principal.is_internal):
            raise ValueError("Human decisions require an authenticated browser session")
        expected = {"run_id", "step_id", "attempt", "artifact_version", "decision"} if human else {"run_id", "fingerprint", "step_id", "attempt"}
        if set(payload) != expected:
            raise ValueError("Unexpected resume/decision fields")
        run_id = text(payload["run_id"], 64)
        async with self.control_lock:
            retained = await asyncio.to_thread(self.store.get, owner, run_id)
            entry = self.entries.get(run_id)
            record = entry["record"] if entry else retained
            if human:
                row = next(
                    (r for r in record.get("checkpoints", []) if r["step_id"] == payload["step_id"]),
                    None,
                )
                if (
                    not row
                    or row["kind"] != "humanCheckpoint"
                    or type(payload["attempt"]) is not int
                    or row["attempt"] != payload["attempt"]
                    or row["artifact_version"] != payload["artifact_version"]
                    or payload["decision"] not in ("approve", "reject")
                ):
                    raise ValueError("Decision does not match exact checkpoint attempt and artifact version")
                status = "approved" if payload["decision"] == "approve" else "rejected"
                if row["status"] != "pending":
                    if row["status"] == status:
                        return {"run_id": run_id, "status": status}
                    raise ValueError("Checkpoint already decided")
            else:
                if payload["fingerprint"] != record["fingerprint"]:
                    raise ValueError("Script, arguments or configuration do not match")
                row = next(
                    (r for r in reversed(record.get("checkpoints", [])) if r["kind"] == "pause" and r["step_id"] == payload["step_id"]),
                    None,
                )
                if not row or type(payload["attempt"]) is not int or payload["attempt"] != row["attempt"]:
                    raise ValueError("Workflow is not paused at this attempt")
                if row["status"] == "resumed":
                    return {"run_id": run_id, "status": "resumed"}
                status = "resumed"
            if not entry or record["status"] != ("waiting_approval" if human else "paused") or entry["cancel"].is_set():
                raise ValueError("Live checkpoint unavailable; restart does not permit resume")
            # Revalidate both the retained capability and this caller's live grant.
            async with asyncio.timeout(5):
                await context.agent_runs.configuration_revision(assistant_ids=sorted(self.config["agents"]))
            await self.check_configuration(entry)
            if entry["cancel"].is_set() or record["status"] not in (
                "paused",
                "waiting_approval",
            ):
                raise ValueError("Workflow stopping")
            if human and row.get("artifact_kind") == "file":
                await asyncio.to_thread(self.store.artifact, owner, run_id, row["artifact_version"])
            previous = copy.deepcopy(row)
            row.update(status=status, decided_by=owner, decided_at=time.time())
            try:
                await self.save(owner, record)
            except BaseException:
                row.clear()
                row.update(previous)
                raise
            entry["gate"].set()
            return {"run_id": run_id, "status": status}
