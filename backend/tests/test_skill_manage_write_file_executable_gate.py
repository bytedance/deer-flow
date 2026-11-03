"""Regression coverage for the write_file executable-content gate in skill_manage.

Executable content is whatever the shared ``deerflow/skills/package_files.py``
rule classifies as code: a file under the *top-level* ``scripts/`` directory of a
skill package, a code-suffixed file anywhere in the package, or an extensionless
file that starts with a shebang (``is_code_file``). Every other support file is
static and must be moderated as such: an ``executable=True`` scan requires an
exact "allow" decision and hard-blocks when the moderation model is unavailable.

Both misclassifications are regressions, so both directions are pinned here:

* over-classifying (the original bug) moderates static support files such as
  ``references/scripts/overview.md`` as executable and over-blocks legitimate
  writes; and
* under-classifying (the ``scripts/``-member-only rule) leaves runnable files
  such as ``references/scripts/helper.py``, ``templates/my-scripts/run.sh`` and
  ``assets/my-scripts/tool.js`` on the static tier, so a ``warn`` decision -- or
  an unavailable moderation model under ``security_fail_closed: false`` -- writes
  code to disk.
"""

import importlib
from pathlib import Path
from types import SimpleNamespace

import anyio
import pytest

skill_manage_module = importlib.import_module("deerflow.tools.skill_manage_tool")

#: Paths the shared code-file rule classifies as executable content, with content
#: that exercises the three clauses: a code suffix outside ``scripts/``, a
#: ``scripts/``-looking directory that is not the package root, and a shebang on
#: an extensionless file.
CODE_SUPPORT_FILES = [
    ("references/scripts/helper.py", "print('hello')\n", "nested-scripts-python"),
    ("templates/my-scripts/run.sh", "#!/bin/bash\necho hello\n", "dir-name-ending-in-scripts"),
    ("assets/my-scripts/tool.js", "console.log('hello');\n", "nested-js"),
    ("references/scripts/hook", "#!/bin/sh\necho hello\n", "extensionless-shebang"),
]

#: Paths that stay on the static tier: Markdown/data support files, plus an
#: extensionless file without a shebang.
STATIC_SUPPORT_FILES = [
    ("references/scripts/overview.md", "# Overview\n\nNotes about the helper scripts.\n", "nested-scripts-markdown"),
    ("templates/my-scripts/setup.md", "# Setup\n\nSteps.\n", "dir-name-ending-in-scripts-markdown"),
    ("references/schema.json", '{"type": "object"}\n', "nested-data"),
    ("references/scripts/notes", "plain notes, no shebang\n", "extensionless-no-shebang"),
]


def _skill_content(name: str, description: str = "Demo skill") -> str:
    return f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n"


async def _async_result(decision: str, reason: str):
    from deerflow.skills.security_scanner import ScanResult

    return ScanResult(decision=decision, reason=reason)


def _make_config(skills_root: Path, *, security_fail_closed: bool = True):
    return SimpleNamespace(
        skills=SimpleNamespace(
            get_skills_path=lambda: skills_root,
            container_path="/mnt/skills",
            use="deerflow.skills.storage.local_skill_storage:LocalSkillStorage",
        ),
        skill_evolution=SimpleNamespace(enabled=True, moderation_model_name=None, security_fail_closed=security_fail_closed),
    )


def _make_runtime(*, thread_id: str = "thread-1", user_id: str = "default"):
    return SimpleNamespace(
        context={"thread_id": thread_id, "user_id": user_id},
        config={"configurable": {"thread_id": thread_id, "user_id": user_id}},
    )


async def _allow_scan(content, *, executable, location, **kwargs):
    return await _async_result("allow", "ok")


def _setup_skill(monkeypatch, tmp_path, *, security_fail_closed: bool = True, scanner=None):
    """Point the skill storage at ``tmp_path`` and create the demo skill.

    The ``create`` call itself is moderated, so ``scanner`` (default: always
    allow) is installed before it runs; tests that need the real moderation
    policy for the ``write_file`` call replace it afterwards.
    """
    skills_root = tmp_path / "skills"
    config = _make_config(skills_root, security_fail_closed=security_fail_closed)
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: config)
    monkeypatch.setattr("deerflow.skills.security_scanner.get_app_config", lambda: config)
    from deerflow.config.paths import Paths

    monkeypatch.setattr("deerflow.config.paths.get_paths", lambda: Paths(base_dir=tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)

    async def _refresh(user_id: str):
        return None

    monkeypatch.setattr(skill_manage_module, "refresh_user_skills_system_prompt_cache_async", _refresh)
    monkeypatch.setattr(skill_manage_module, "scan_skill_content", scanner or _allow_scan)

    runtime = _make_runtime(user_id="default")
    anyio.run(skill_manage_module.skill_manage_tool.coroutine, runtime, "create", "demo-skill", _skill_content("demo-skill"))
    skill_dir = tmp_path / "users" / "default" / "skills" / "custom" / "demo-skill"
    return runtime, skill_dir


def _setup_with_scan_recorder(monkeypatch, tmp_path, *, decision: str = "allow"):
    """Create the demo skill; return (runtime, scan_calls, skill_dir).

    ``scan_calls`` records the moderation kwargs of every ``scan_skill_content``
    call made after the initial create, so tests can pin the ``executable``
    classification of a write_file path and the decision the gate is handed.
    """
    scan_calls = []

    async def _scan(content, *, executable, location, **kwargs):
        scan_calls.append({"executable": executable, "location": location})
        return await _async_result(decision, f"stubbed {decision}")

    runtime, skill_dir = _setup_skill(monkeypatch, tmp_path, scanner=_scan)
    scan_calls.clear()
    return runtime, scan_calls, skill_dir


def _use_real_moderation_and_make_it_unavailable(monkeypatch, tmp_path, *, security_fail_closed: bool):
    """Create the demo skill, then hand the gate the real scanner with no model."""
    runtime, skill_dir = _setup_skill(monkeypatch, tmp_path, security_fail_closed=security_fail_closed)

    from deerflow.skills.security_scanner import scan_skill_content

    monkeypatch.setattr(skill_manage_module, "scan_skill_content", scan_skill_content)
    monkeypatch.setattr("deerflow.skills.security_scanner.create_chat_model", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("moderation provider unavailable")))
    return runtime, skill_dir


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


@pytest.mark.parametrize(
    "path",
    ["scripts/run.sh", "scripts/sub/run.sh", "./scripts/run.sh"],
    ids=["top-level-script", "nested-under-scripts", "dot-prefixed"],
)
def test_write_file_top_level_scripts_file_is_scanned_as_executable(monkeypatch, tmp_path, path):
    runtime, scan_calls, skill_dir = _setup_with_scan_recorder(monkeypatch, tmp_path)
    content = "#!/bin/bash\necho hello\n"

    anyio.run(
        skill_manage_module.skill_manage_tool.coroutine,
        runtime,
        "write_file",
        "demo-skill",
        content,
        path,
    )

    assert (skill_dir / Path(path)).read_text(encoding="utf-8") == content
    assert scan_calls == [{"executable": True, "location": f"demo-skill/{path}"}], f"file '{path}' under the top-level scripts/ directory must be moderated as executable content; got {scan_calls}"


@pytest.mark.parametrize(
    ("path", "content"),
    [(path, content) for path, content, _ in CODE_SUPPORT_FILES],
    ids=[case for _, _, case in CODE_SUPPORT_FILES],
)
def test_write_file_code_support_file_outside_top_level_scripts_is_scanned_as_executable(monkeypatch, tmp_path, path, content):
    runtime, scan_calls, skill_dir = _setup_with_scan_recorder(monkeypatch, tmp_path)

    result = anyio.run(
        skill_manage_module.skill_manage_tool.coroutine,
        runtime,
        "write_file",
        "demo-skill",
        content,
        path,
    )

    assert f"Wrote '{path}'" in result
    assert scan_calls == [{"executable": True, "location": f"demo-skill/{path}"}], f"code file '{path}' must be moderated as executable content by the shared code-file rule; got {scan_calls}"


@pytest.mark.parametrize(
    ("path", "content"),
    [(path, content) for path, content, _ in STATIC_SUPPORT_FILES],
    ids=[case for _, _, case in STATIC_SUPPORT_FILES],
)
def test_write_file_non_code_support_file_stays_static(monkeypatch, tmp_path, path, content):
    runtime, scan_calls, skill_dir = _setup_with_scan_recorder(monkeypatch, tmp_path)

    anyio.run(
        skill_manage_module.skill_manage_tool.coroutine,
        runtime,
        "write_file",
        "demo-skill",
        content,
        path,
    )

    assert (skill_dir / Path(path)).read_text(encoding="utf-8") == content
    assert scan_calls == [{"executable": False, "location": f"demo-skill/{path}"}], f"non-code support file '{path}' must stay on the static tier; got {scan_calls}"


@pytest.mark.parametrize(
    ("path", "content"),
    [(path, content) for path, content, _ in CODE_SUPPORT_FILES],
    ids=[case for _, _, case in CODE_SUPPORT_FILES],
)
def test_write_file_rejects_code_support_file_when_moderation_warns(monkeypatch, tmp_path, path, content):
    runtime, scan_calls, skill_dir = _setup_with_scan_recorder(monkeypatch, tmp_path, decision="warn")

    with pytest.raises(ValueError, match="Security scan rejected executable content"):
        anyio.run(
            skill_manage_module.skill_manage_tool.coroutine,
            runtime,
            "write_file",
            "demo-skill",
            content,
            path,
        )

    assert not (skill_dir / Path(path)).exists(), f"a warn decision must not write code file '{path}'"
    assert scan_calls == [{"executable": True, "location": f"demo-skill/{path}"}], f"code file '{path}' must reach the gate as executable content; got {scan_calls}"


@pytest.mark.parametrize(
    ("path", "content"),
    [(path, content) for path, content, _ in STATIC_SUPPORT_FILES],
    ids=[case for _, _, case in STATIC_SUPPORT_FILES],
)
def test_write_file_writes_support_file_when_moderation_warns(monkeypatch, tmp_path, path, content):
    runtime, scan_calls, skill_dir = _setup_with_scan_recorder(monkeypatch, tmp_path, decision="warn")

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
    assert scan_calls == [{"executable": False, "location": f"demo-skill/{path}"}], f"static support file '{path}' must stay writable on a warn decision; got {scan_calls}"


@pytest.mark.parametrize(
    ("path", "content"),
    [(path, content) for path, content, _ in CODE_SUPPORT_FILES],
    ids=[case for _, _, case in CODE_SUPPORT_FILES],
)
def test_write_file_rejects_code_support_file_when_moderation_unavailable_and_fail_open(monkeypatch, tmp_path, path, content):
    # ``security_fail_closed: false`` only relaxes *non-executable* content; code
    # stays blocked because an ``executable=True`` scan never fails open.
    runtime, skill_dir = _use_real_moderation_and_make_it_unavailable(monkeypatch, tmp_path, security_fail_closed=False)

    with pytest.raises(ValueError, match="Security scan blocked the write"):
        anyio.run(
            skill_manage_module.skill_manage_tool.coroutine,
            runtime,
            "write_file",
            "demo-skill",
            content,
            path,
        )

    assert not (skill_dir / Path(path)).exists(), f"an unavailable moderation model must not write code file '{path}'"


@pytest.mark.parametrize(
    ("path", "content"),
    [(path, content) for path, content, _ in STATIC_SUPPORT_FILES],
    ids=[case for _, _, case in STATIC_SUPPORT_FILES],
)
def test_write_file_writes_support_file_when_moderation_unavailable_and_fail_open(monkeypatch, tmp_path, path, content):
    runtime, skill_dir = _use_real_moderation_and_make_it_unavailable(monkeypatch, tmp_path, security_fail_closed=False)

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


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("scripts/run.sh", True),
        ("scripts/sub/run.sh", True),
        ("scripts\\run.sh", True),
        # The shared predicate treats a bare ``scripts`` as a member too; the
        # storage layer rejects it as a support path before classification.
        ("scripts", True),
        ("references/scripts/overview.md", False),
        ("/scripts/run.sh", False),
    ],
)
def test_is_scripts_member_uses_the_shared_posix_rule(path, expected):
    from deerflow.skills.package_files import is_scripts_member

    assert is_scripts_member(path) is expected


@pytest.mark.parametrize(
    ("path", "head", "expected"),
    [
        ("references/scripts/helper.py", b"print('hello')\n", True),
        ("assets/my-scripts/tool.js", b"console.log(1);\n", True),
        ("references/scripts/hook", b"#!/bin/sh\n", True),
        ("references/scripts/hook", b"plain notes\n", False),
        ("references/scripts/overview.md", b"# Overview\n", False),
        ("scripts/run.sh", b"echo hello\n", True),
    ],
)
def test_is_code_file_covers_code_suffixes_and_shebangs_anywhere_in_the_package(path, head, expected):
    from deerflow.skills.package_files import is_code_file

    assert is_code_file(path, head) is expected
