"""Persistence writers publish the caller's bytes on every host (#7174).

Python's default text mode translates ``\\n`` into ``os.linesep`` on write, so
on a Windows host every one of these writers stored CRLF for content the caller
submitted with LF. Readers use universal newlines (or decode explicitly), so
the mismatch stayed invisible: the API returned LF, the file held CRLF, and a
skill-history record's ``prev_content`` described a revision no API view could
return.

Each test emulates the Windows translation instead of running on Windows, so
the regression is exercised on the Linux CI shards too.
"""

from __future__ import annotations

import builtins
import io
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

from deerflow.config.paths import Paths, get_paths
from deerflow.persistence.agents.file import FileAgentStore
from deerflow.persistence.managed_subagents import ManagedSubagentDefinition
from deerflow.persistence.managed_subagents.file import FileManagedSubagentStore
from deerflow.runtime.user_context import get_effective_user_id
from deerflow.skills.storage import get_or_new_skill_storage, reset_skill_storage
from deerflow.skills.storage.user_scoped_skill_storage import UserScopedSkillStorage
from deerflow.tools.builtins.setup_agent_tool import _publish_text

LF_CONTENT = "---\nname: demo-skill\ndescription: Demo skill\n---\n\n# Demo\nsecond line\n"


@contextmanager
def _windows_text_writes(monkeypatch):
    """Make text-mode writes translate ``\\n`` the way Windows does by default.

    ``Path.open``, ``Path.write_text``, ``tempfile.NamedTemporaryFile`` and
    ``os.fdopen`` all funnel through ``io.open``, so one patch covers every
    writer under test. Binary modes are left alone.
    """
    real_open = io.open

    def translating_open(
        file,
        mode="r",
        buffering=-1,
        encoding=None,
        errors=None,
        newline=None,
        closefd=True,
        opener=None,
    ):
        # ``Path.open`` passes newline positionally while ``os.fdopen`` and
        # ``NamedTemporaryFile`` pass it by keyword, so both are spelled out.
        if "b" not in mode and any(flag in mode for flag in "wax+") and newline is None:
            newline = "\r\n"
        return real_open(file, mode, buffering, encoding, errors, newline, closefd, opener)

    monkeypatch.setattr(io, "open", translating_open)
    # ``builtins.open`` is the same function object under a separate binding;
    # writers that call the builtin directly must be translated too.
    monkeypatch.setattr(builtins, "open", translating_open)
    try:
        yield
    finally:
        monkeypatch.setattr(io, "open", real_open)
        monkeypatch.setattr(builtins, "open", real_open)


@pytest.fixture(autouse=True)
def _reset_skill_storages():
    reset_skill_storage()
    yield
    reset_skill_storage()


@pytest.fixture()
def storage(tmp_path: Path):
    return get_or_new_skill_storage(skills_path=str(tmp_path / "skills"))


@pytest.fixture()
def user_storage(tmp_path: Path):
    with patch("deerflow.config.paths.get_paths", return_value=Paths(base_dir=tmp_path)):
        with patch("deerflow.config.paths._paths", None):
            yield UserScopedSkillStorage("test-user", host_path=str(tmp_path))


def test_local_skill_write_stores_lf_bytes(storage, monkeypatch) -> None:
    with _windows_text_writes(monkeypatch):
        storage.write_custom_skill("demo-skill", "SKILL.md", LF_CONTENT)

    stored = storage.get_custom_skill_dir("demo-skill") / "SKILL.md"
    assert stored.read_bytes() == LF_CONTENT.encode("utf-8")


def test_skill_history_records_lf_bytes(storage, monkeypatch) -> None:
    """A translated record boundary makes the stored revision unreproducible.

    ``prev_content`` is read back raw for rollback; if the record separating it
    from the next entry became CRLF, the history described text the skill API
    never returns.
    """
    storage.write_custom_skill("demo-skill", "SKILL.md", LF_CONTENT)
    with _windows_text_writes(monkeypatch):
        storage.append_history("demo-skill", {"action": "update", "prev_content": LF_CONTENT})

    raw = storage.get_skill_history_file("demo-skill").read_bytes()
    assert b"\r\n" not in raw
    assert raw.endswith(b"\n")
    assert raw.count(b"\n") == 1


def test_user_scoped_skill_write_stores_lf_bytes(user_storage, monkeypatch) -> None:
    with _windows_text_writes(monkeypatch):
        user_storage.write_custom_skill("demo-skill", "SKILL.md", LF_CONTENT)

    stored = user_storage.get_custom_skill_dir("demo-skill") / "SKILL.md"
    assert stored.read_bytes() == LF_CONTENT.encode("utf-8")


def test_user_scoped_skill_states_store_lf_bytes(user_storage, tmp_path: Path, monkeypatch) -> None:
    with _windows_text_writes(monkeypatch):
        user_storage.set_skill_enabled_state("demo-skill", False)

    states_files = list(tmp_path.rglob("_skill_states.json"))
    assert states_files, "skill state file was not written"
    assert b"\r\n" not in states_files[0].read_bytes()


def test_agent_store_soul_keeps_lf_bytes(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    soul = "# Persona\nAnswer briefly.\n"
    with _windows_text_writes(monkeypatch):
        FileAgentStore().create("lf-agent", {"description": "demo"}, soul)

    soul_path = get_paths().user_agent_dir(get_effective_user_id(), "lf-agent") / "SOUL.md"
    assert soul_path.read_bytes() == soul.encode("utf-8")


def test_managed_subagent_file_store_keeps_lf_bytes(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    definition = ManagedSubagentDefinition(
        name="lf-researcher",
        description="Researches a bounded topic",
        system_prompt="Line one\nLine two\n",
    )
    with _windows_text_writes(monkeypatch):
        FileManagedSubagentStore().create(definition)

    stored = get_paths().managed_subagent_file("lf-researcher")
    assert stored.read_bytes() == (definition.model_dump_json(indent=2) + "\n").encode("utf-8")


def test_setup_agent_publish_keeps_lf_bytes(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "SOUL.md"
    with _windows_text_writes(monkeypatch):
        _publish_text(target, "# Persona\nStay terse.\n")

    assert target.read_bytes() == b"# Persona\nStay terse.\n"


@pytest.mark.asyncio
async def test_user_profile_update_keeps_lf_bytes(tmp_path: Path, monkeypatch) -> None:
    from app.gateway.routers.agents import UserProfileUpdateRequest, update_user_profile
    from deerflow.config.agents_api_config import load_agents_api_config_from_dict

    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    load_agents_api_config_from_dict({"enabled": True})
    try:
        with _windows_text_writes(monkeypatch):
            await update_user_profile(UserProfileUpdateRequest(content="I prefer terse answers.\n"))
    finally:
        load_agents_api_config_from_dict({})

    user_md = get_paths().user_md_file(get_effective_user_id())
    assert user_md.read_bytes() == b"I prefer terse answers.\n"


def test_skill_markdown_validation_reads_lf_bytes(monkeypatch) -> None:
    """The frontmatter validator has to see the bytes the caller submitted."""
    import deerflow.skills.validation as validation
    from deerflow.skills.storage.skill_storage import SkillStorage

    seen: list[bytes] = []

    def fake_validate(skill_dir: Path):
        seen.append((Path(skill_dir) / "SKILL.md").read_bytes())
        return True, "", "demo-skill"

    monkeypatch.setattr(validation, "_validate_skill_frontmatter", fake_validate)
    with _windows_text_writes(monkeypatch):
        SkillStorage.validate_skill_markdown_content("demo-skill", LF_CONTENT)

    assert seen == [LF_CONTENT.encode("utf-8")]


@pytest.mark.asyncio
async def test_static_skill_scan_reads_lf_bytes(monkeypatch) -> None:
    """The static scan has to see the bytes the caller submitted."""
    import app.gateway.routers.skills as skills_router

    seen: list[bytes] = []

    def fake_scan(skill_dir, *, skill_name, app_config):
        seen.append((Path(skill_dir) / "SKILL.md").read_bytes())
        return []

    monkeypatch.setattr(skills_router, "enforce_static_scan", fake_scan)
    with _windows_text_writes(monkeypatch):
        findings = await skills_router._scan_static_skill_markdown_or_raise(
            "demo-skill",
            LF_CONTENT,
            app_config=None,
        )

    assert findings == []
    assert seen == [LF_CONTENT.encode("utf-8")]


@pytest.mark.asyncio
@pytest.mark.parametrize("existing", [False, True], ids=["new-skill", "existing-skill"])
@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "crlf"])
async def test_skill_manage_static_scan_matches_stored_bytes(storage, monkeypatch, existing, newline) -> None:
    """Agent-managed candidates must be scanned exactly as storage publishes them."""
    import deerflow.tools.skill_manage_tool as skill_manage

    if existing:
        storage.write_custom_skill("demo-skill", "SKILL.md", LF_CONTENT)
        storage.write_custom_skill("demo-skill", "notes.txt", "Keep this file.\n")
    updates = {
        "SKILL.md": LF_CONTENT.replace("Demo skill", "中文 skill").replace("\n", newline),
        "scripts/helper.py": f'print("你好"){newline}',
    }
    seen: list[dict[str, bytes]] = []

    def fake_scan(skill_dir, *, skill_name):
        assert skill_name == "demo-skill"
        seen.append({relative: (Path(skill_dir) / relative).read_bytes() for relative in updates})
        if existing:
            assert (Path(skill_dir) / "notes.txt").read_bytes() == b"Keep this file.\n"
        return []

    monkeypatch.setattr(skill_manage, "enforce_static_scan", fake_scan)
    with _windows_text_writes(monkeypatch):
        findings = await skill_manage._scan_static_candidate_or_raise("demo-skill", updates, storage if existing else None)
        for relative, content in updates.items():
            storage.write_custom_skill("demo-skill", relative, content)

    published = {relative: (storage.get_custom_skill_dir("demo-skill") / relative).read_bytes() for relative in updates}
    assert findings == []
    assert published == {relative: content.encode("utf-8") for relative, content in updates.items()}
    assert seen == [published]
