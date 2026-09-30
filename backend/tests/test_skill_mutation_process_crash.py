"""Real SIGKILL verifies journal/file ordering, not exception-only simulation."""

import asyncio
import json
import os
import signal
import sys
from pathlib import Path

import pytest
from test_skill_mutations import CONTENT, NEW, host, stage  # noqa: F401 -- shared real-SQLite fixture


@pytest.mark.skipif(os.name != "posix", reason="P0 publication supports POSIX only")
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "boundary,expected",
    [
        ("prepared", "ABORTED"),
        ("written", "ABORTED"),
        ("file_synced", "ABORTED"),
        ("renamed", "APPLIED"),
        ("directory_synced", "APPLIED"),
        ("response_lost", "APPLIED"),
    ],
)
async def test_sigkill_recovers_without_replay_or_double_version(host, boundary, expected):  # noqa: F811 -- injected fixture
    proposal = await stage(host)
    await host.service.check(proposal_id=proposal.proposal_id)
    args = {
        "base": str(host.storage._paths.base_dir),
        "skills": str(host.storage.get_skills_root_path()),
        "database": str(host.sessions.kw["bind"].url),
        "grant": host.binding.access.model_dump(mode="json"),
        "proposal": proposal.proposal_id,
        "boundary": boundary,
    }
    child = await asyncio.create_subprocess_exec(sys.executable, str(Path(__file__).parent / "fixtures" / "skill_mutation_crash_worker.py"), json.dumps(args), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    _, stderr = await asyncio.wait_for(child.communicate(), timeout=30)
    assert child.returncode == -signal.SIGKILL, stderr.decode()
    await asyncio.to_thread(host.recovery.recover_owner, "owner")
    operation = await host.service.find_operation(idempotency_key="crash-commit")
    assert operation.publication == expected
    expected_content = NEW if expected == "APPLIED" else CONTENT
    assert host.storage.get_custom_skill_file("example").read_text(encoding="utf-8") == expected_content
    first_revision = host.runtime.read_revision(host.storage, "example")
    await asyncio.to_thread(host.recovery.recover_owner, "owner")
    assert host.runtime.read_revision(host.storage, "example") == first_revision
    assert first_revision == (operation.after_revision if expected == "APPLIED" else operation.before_revision)
    assert not list(host.storage.get_custom_skill_dir("example").parent.glob(".host-mutation-*"))
