"""Regression coverage for the write_file executable-content gate in skill_manage.

Only files under the *top-level* ``scripts/`` directory of a skill package are
executable content (the ``scripts/`` member rule from
``deerflow/skills/package_files.py``).  Every other support file is static and
must be moderated as such: an ``executable=True`` scan requires an exact
"allow" decision and hard-blocks when the moderation model is unavailable,
so misclassifying a support file over-blocks legitimate writes.
"""

import importlib
from pathlib import Path
from types import SimpleNamespace

import anyio
import pytest

skill_manage_module = importlib.import_module("deerflow.tools.skill_manage_tool")


def _skill_content(name: str, description: str = "Demo skill") -> str:
    return f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n"


async def _async_result(decision: str, reason: str):
    from deerflow.skills.security_scanner import ScanResult

    return ScanResult(decision=decision, reason=reason)


def _make_config(skills_root: Path):
    return SimpleNamespace(
        skills=SimpleNamespace(
            get_skills_path=lambda: skills_root,
            container_path="/mnt/skills",
            use="deerflow.skills.storage.local_skill_storage:LocalSkillStorage",
        ),
        skill_evolution=SimpleNamespace(enabled=True, moderation_model_name=None),
    )


def _make_runtime(*, thread_id: str = "thread-1", user_id: str = "default"):
    return SimpleNamespace(
        context={"thread_id": thread_id, "user_id": user_id},
        config={"configurable": {"thread_id": thread_id, "user_id": user_id}},
    )


def _setup_with_scan_recorder(monkeypatch, tmp_path):
    """Create the demo skill; return (runtime, scan_calls, skill_dir).

    ``scan_calls`` records the moderation kwargs of every ``scan_skill_content``
    call made after the initial create, so tests can pin the ``executable``
    classification of a write_file path.
    """
    skills_root = tmp_path / "skills"
    config = _make_config(skills_root)
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: config)
    monkeypatch.setattr("deerflow.skills.security_scanner.get_app_config", lambda: config)
    from deerflow.config.paths import Paths

    monkeypatch.setattr("deerflow.config.paths.get_paths", lambda: Paths(base_dir=tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)

    async def _refresh(user_id: str):
        return None

    scan_calls = []

    async def _scan(content, *, executable, location, **kwargs):
        scan_calls.append({"executable": executable, "location": location})
        return await _async_result("allow", "ok")

    monkeypatch.setattr(skill_manage_module, "refresh_user_skills_system_prompt_cache_async", _refresh)
    monkeypatch.setattr(skill_manage_module, "scan_skill_content", _scan)

    runtime = _make_runtime(user_id="default")
    anyio.run(skill_manage_module.skill_manage_tool.coroutine, runtime, "create", "demo-skill", _skill_content("demo-skill"))
    scan_calls.clear()
    skill_dir = tmp_path / "users" / "default" / "skills" / "custom" / "demo-skill"
    return runtime, scan_calls, skill_dir


@pytest.mark.parametrize(
    "path",
    ["references/scripts/overview.md", "templates/my-scripts/setup.md"],
    ids=["nested-scripts-dir", "dir-name-ending-in-scripts"],
)
def test_write_file_support_path_containing_scripts_substring_is_scanned_as_static(monkeypatch, tmp_path, path):
    runtime, scan_calls, skill_dir = _setup_with_scan_recorder(monkeypatch, tmp_path)
    content = "# Overview\n\nNotes about the helper scripts.\n"

    result = anyio.run(
        skill_manage_module.skill_manage_tool.coroutine,
        runtime,
        "write_file",
        "demo-skill",
        content,
        path,
    )

    assert f"Wrote '{path}'" in result
    assert (skill_dir / Path(path)).read_text(encoding="utf-8") == content
    assert scan_calls == [{"executable": False, "location": f"demo-skill/{path}"}], f"support file '{path}' must be moderated as static content (executable=False); got {scan_calls}"


def test_write_file_top_level_scripts_file_is_scanned_as_executable(monkeypatch, tmp_path):
    runtime, scan_calls, skill_dir = _setup_with_scan_recorder(monkeypatch, tmp_path)
    content = "#!/bin/bash\necho hello\n"

    anyio.run(
        skill_manage_module.skill_manage_tool.coroutine,
        runtime,
        "write_file",
        "demo-skill",
        content,
        "scripts/run.sh",
    )

    assert (skill_dir / "scripts" / "run.sh").read_text(encoding="utf-8") == content
    assert scan_calls == [{"executable": True, "location": "demo-skill/scripts/run.sh"}], f"top-level scripts/ file must be moderated as executable content; got {scan_calls}"
