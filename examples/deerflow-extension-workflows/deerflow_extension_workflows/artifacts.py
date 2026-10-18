"""Version-only file capture, review and consumption. Never reopen source paths."""

import asyncio
import base64
import re
from pathlib import PurePosixPath


class Artifacts:
    async def capture(self, entry, message):
        from .service import text

        payload = message.get("payload")
        if not isinstance(payload, dict) or set(payload) != {"stepId", "sourceStepId", "path"}:
            raise ValueError("captureArtifact requires stepId, sourceStepId and path")
        record, owner = entry["record"], entry["owner"]
        step_id = text(payload["stepId"], 80)
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", step_id) or any(s["step_id"] == step_id for s in record["steps"] + record["checkpoints"] + record["artifacts"]):
            raise ValueError("Invalid or reused artifact step ID")
        source = next((s for s in record["steps"] if s["step_id"] == payload["sourceStepId"] and s["status"] == "completed"), None)
        if source is None:
            raise ValueError("Artifact source must be a completed Agent step")
        path = text(payload["path"], 1000)
        name = text(PurePosixPath(path).name, 160)
        async with asyncio.timeout(10):
            content = await entry["runs"].read_artifact(thread_id=source["thread_id"], path=path)
        info = await asyncio.to_thread(self.store.capture_artifact, owner, record["id"], step_id, name, content)
        info.update(source_step_id=source["step_id"], source_run_id=source["run_id"], source_thread_id=source["thread_id"])
        record["artifacts"].append(info)
        await self.save(owner, record)
        return {"id": message["id"], "value": {**info, "artifactVersion": info["version"]}}

    @staticmethod
    def approved_artifact(record, version):
        return any(c.get("artifact_kind") == "file" and c.get("artifact_version") == version and c["status"] == "approved" for c in record.get("checkpoints", []))

    async def artifact_chunk(self, owner, payload, *, require_approval):
        from .service import text

        if set(payload) - {"run_id", "version", "offset"}:
            raise ValueError("Unexpected artifact read fields")
        run_id, version = text(payload.get("run_id"), 64), text(payload.get("version"), 64)
        record = await asyncio.to_thread(self.store.get, owner, run_id)
        if require_approval and not self.approved_artifact(record, version):
            raise ValueError("File version has not been approved")
        offset = payload.get("offset", 0)
        if type(offset) is not int or offset < 0:
            raise ValueError("Invalid artifact offset")
        info, content = await asyncio.to_thread(self.store.artifact, owner, run_id, version)
        if offset > len(content):
            raise ValueError("Offset exceeds artifact size")
        end = min(offset + 16384, len(content))
        return {**info, "offset": offset, "next_offset": end if end < len(content) else None, "content_base64": base64.b64encode(content[offset:end]).decode("ascii")}

    async def get_artifact(self, payload, context):
        """Browser review reads the same stored bytes as downstream consumers."""
        from deerflow_extension_api.plugins import ToolContext

        if isinstance(context, ToolContext):
            raise ValueError("Use the approved-artifact consumer tool")
        return await self.artifact_chunk(self.owner(context), payload, require_approval=False)

    async def read_artifact(self, payload, context):
        return await self.artifact_chunk(self.owner(context), payload, require_approval=True)

    async def consume(self, entry, message):
        payload = message.get("payload")
        if not isinstance(payload, dict) or set(payload) - {"artifactVersion", "offset"}:
            raise ValueError("readArtifact requires artifactVersion and optional offset")
        result = await self.artifact_chunk(entry["owner"], {"run_id": entry["record"]["id"], "version": payload.get("artifactVersion"), "offset": payload.get("offset", 0)}, require_approval=True)
        return {"id": message["id"], "value": result}
