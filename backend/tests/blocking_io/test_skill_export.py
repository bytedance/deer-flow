"""The real exporter, compression, response reads and cleanup stay off-loop."""

import asyncio

import pytest

from app.gateway.skill_export import SkillExportResponse, run_export_work
from deerflow.skills.export import build_skill_export, export_manifest
from deerflow.skills.storage.local_skill_storage import LocalSkillStorage


@pytest.fixture
def storage(tmp_path):
    storage = LocalSkillStorage(host_path=str(tmp_path))
    root = storage.get_custom_skill_dir("demo")
    root.mkdir(parents=True)
    (root / "SKILL.md").write_text("---\nname: demo\ndescription: Offline fixture\n---\nbody", encoding="utf-8")
    return storage


@pytest.mark.asyncio
async def test_export_worker_and_response_are_off_loop(storage):
    manifest, lease = await run_export_work(lambda cancel: export_manifest(storage, "demo", cancel))
    lease.release()
    archive, lease = await run_export_work(lambda cancel: build_skill_export(storage, "demo", manifest["revision"], cancel))
    response = SkillExportResponse(archive, "demo", lease)
    sent = []

    async def send(event):
        sent.append(event)

    async def receive():
        await asyncio.Event().wait()

    await response({"type": "http", "asgi": {"spec_version": "2.4"}}, receive, send)
    assert sent[0]["status"] == 200
    assert b"".join(event.get("body", b"") for event in sent).startswith(b"PK")
    assert archive.file.closed
