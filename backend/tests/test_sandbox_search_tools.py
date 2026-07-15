import json
from types import SimpleNamespace
from unittest.mock import patch

from deerflow.community.aio_sandbox.aio_sandbox import AioSandbox
from deerflow.config.paths import Paths
from deerflow.sandbox.local.local_sandbox import LocalSandbox, PathMapping
from deerflow.sandbox.search import GrepMatch, find_glob_matches, find_grep_matches
from deerflow.sandbox.tools import glob_tool, grep_tool, ls_tool


def _make_runtime(tmp_path):
    workspace = tmp_path / "workspace"
    uploads = tmp_path / "uploads"
    outputs = tmp_path / "outputs"
    workspace.mkdir()
    uploads.mkdir()
    outputs.mkdir()
    return SimpleNamespace(
        state={
            "sandbox": {"sandbox_id": "local"},
            "thread_data": {
                "workspace_path": str(workspace),
                "uploads_path": str(uploads),
                "outputs_path": str(outputs),
            },
        },
        context={"thread_id": "thread-1"},
    )


def test_glob_tool_returns_virtual_paths_and_ignores_common_dirs(tmp_path, monkeypatch) -> None:
    runtime = _make_runtime(tmp_path)
    workspace = tmp_path / "workspace"
    (workspace / "app.py").write_text("print('hi')\n", encoding="utf-8")
    (workspace / "pkg").mkdir()
    (workspace / "pkg" / "util.py").write_text("print('util')\n", encoding="utf-8")
    (workspace / "node_modules").mkdir()
    (workspace / "node_modules" / "skip.py").write_text("ignored\n", encoding="utf-8")

    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: LocalSandbox(id="local"))

    result = glob_tool.func(
        runtime=runtime,
        description="find python files",
        pattern="**/*.py",
        path="/mnt/user-data/workspace",
    )

    assert "/mnt/user-data/workspace/app.py" in result
    assert "/mnt/user-data/workspace/pkg/util.py" in result
    assert "node_modules" not in result
    assert str(workspace) not in result


def test_glob_tool_supports_skills_virtual_paths(tmp_path, monkeypatch) -> None:
    runtime = _make_runtime(tmp_path)
    skills_dir = tmp_path / "skills"
    (skills_dir / "public" / "demo").mkdir(parents=True)
    (skills_dir / "public" / "demo" / "SKILL.md").write_text("# Demo\n", encoding="utf-8")

    sandbox = LocalSandbox(
        id="local",
        path_mappings=[
            PathMapping(container_path="/mnt/skills", local_path=str(skills_dir), read_only=True),
        ],
    )
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: sandbox)

    result = glob_tool.func(
        runtime=runtime,
        description="find skills",
        pattern="**/SKILL.md",
        path="/mnt/skills",
    )

    assert "/mnt/skills/public/demo/SKILL.md" in result
    assert str(skills_dir) not in result


def test_grep_tool_filters_by_glob_and_skips_binary_files(tmp_path, monkeypatch) -> None:
    runtime = _make_runtime(tmp_path)
    workspace = tmp_path / "workspace"
    (workspace / "main.py").write_text("TODO = 'ship it'\nprint(TODO)\n", encoding="utf-8")
    (workspace / "notes.txt").write_text("TODO in txt should be filtered\n", encoding="utf-8")
    (workspace / "image.bin").write_bytes(b"\0binary TODO")

    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: LocalSandbox(id="local"))

    result = grep_tool.func(
        runtime=runtime,
        description="find todo references",
        pattern="TODO",
        path="/mnt/user-data/workspace",
        glob="**/*.py",
    )

    assert "/mnt/user-data/workspace/main.py:1: TODO = 'ship it'" in result
    assert "notes.txt" not in result
    assert "image.bin" not in result
    assert str(workspace) not in result


def test_grep_tool_truncates_results(tmp_path, monkeypatch) -> None:
    runtime = _make_runtime(tmp_path)
    workspace = tmp_path / "workspace"
    (workspace / "main.py").write_text("TODO one\nTODO two\nTODO three\n", encoding="utf-8")

    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: LocalSandbox(id="local"))
    # Prevent config.yaml tool config from overriding the caller-supplied max_results=2.
    monkeypatch.setattr("deerflow.sandbox.tools.get_app_config", lambda: SimpleNamespace(get_tool_config=lambda name: None))

    result = grep_tool.func(
        runtime=runtime,
        description="limit matches",
        pattern="TODO",
        path="/mnt/user-data/workspace",
        max_results=2,
    )

    assert "Found 2 matches under /mnt/user-data/workspace (showing first 2)" in result
    assert "TODO one" in result
    assert "TODO two" in result
    assert "TODO three" not in result
    assert "Results truncated." in result


def test_glob_tool_include_dirs_filters_nested_ignored_paths(tmp_path, monkeypatch) -> None:
    runtime = _make_runtime(tmp_path)
    workspace = tmp_path / "workspace"
    (workspace / "src").mkdir()
    (workspace / "src" / "main.py").write_text("x\n", encoding="utf-8")
    (workspace / "node_modules").mkdir()
    (workspace / "node_modules" / "lib").mkdir()

    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: LocalSandbox(id="local"))

    result = glob_tool.func(
        runtime=runtime,
        description="find dirs",
        pattern="**",
        path="/mnt/user-data/workspace",
        include_dirs=True,
    )

    assert "src" in result
    assert "node_modules" not in result


def test_grep_tool_literal_mode(tmp_path, monkeypatch) -> None:
    runtime = _make_runtime(tmp_path)
    workspace = tmp_path / "workspace"
    (workspace / "file.py").write_text("price = (a+b)\nresult = a+b\n", encoding="utf-8")

    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: LocalSandbox(id="local"))

    # literal=True should treat (a+b) as a plain string, not a regex group
    result = grep_tool.func(
        runtime=runtime,
        description="literal search",
        pattern="(a+b)",
        path="/mnt/user-data/workspace",
        literal=True,
    )

    assert "price = (a+b)" in result
    assert "result = a+b" not in result


def test_grep_tool_case_sensitive(tmp_path, monkeypatch) -> None:
    runtime = _make_runtime(tmp_path)
    workspace = tmp_path / "workspace"
    (workspace / "file.py").write_text("TODO: fix\ntodo: also fix\n", encoding="utf-8")

    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: LocalSandbox(id="local"))

    result = grep_tool.func(
        runtime=runtime,
        description="case sensitive search",
        pattern="TODO",
        path="/mnt/user-data/workspace",
        case_sensitive=True,
    )

    assert "TODO: fix" in result
    assert "todo: also fix" not in result


def test_grep_tool_invalid_regex_returns_error(tmp_path, monkeypatch) -> None:
    runtime = _make_runtime(tmp_path)

    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: LocalSandbox(id="local"))

    result = grep_tool.func(
        runtime=runtime,
        description="bad pattern",
        pattern="[invalid",
        path="/mnt/user-data/workspace",
    )

    assert "Invalid regex pattern" in result


def test_aio_sandbox_glob_include_dirs_filters_nested_ignored(monkeypatch) -> None:
    with patch("deerflow.community.aio_sandbox.aio_sandbox.AioSandboxClient"):
        sandbox = AioSandbox(id="test-sandbox", base_url="http://localhost:8080")
    monkeypatch.setattr(
        sandbox._client.file,
        "list_path",
        lambda **kwargs: SimpleNamespace(
            data=SimpleNamespace(
                files=[
                    SimpleNamespace(name="src", path="/mnt/workspace/src"),
                    SimpleNamespace(name="node_modules", path="/mnt/workspace/node_modules"),
                    # child of node_modules — should be filtered via should_ignore_path
                    SimpleNamespace(name="lib", path="/mnt/workspace/node_modules/lib"),
                ]
            )
        ),
    )

    matches, truncated = sandbox.glob("/mnt/workspace", "**", include_dirs=True)

    assert "/mnt/workspace/src" in matches
    assert "/mnt/workspace/node_modules" not in matches
    assert "/mnt/workspace/node_modules/lib" not in matches
    assert truncated is False


def test_aio_sandbox_grep_invalid_regex_raises() -> None:
    with patch("deerflow.community.aio_sandbox.aio_sandbox.AioSandboxClient"):
        sandbox = AioSandbox(id="test-sandbox", base_url="http://localhost:8080")

    import re

    try:
        sandbox.grep("/mnt/workspace", "[invalid")
        assert False, "Expected re.error"
    except re.error:
        pass


def test_aio_sandbox_glob_parses_json(monkeypatch) -> None:
    with patch("deerflow.community.aio_sandbox.aio_sandbox.AioSandboxClient"):
        sandbox = AioSandbox(id="test-sandbox", base_url="http://localhost:8080")
    monkeypatch.setattr(
        sandbox._client.file,
        "find_files",
        lambda **kwargs: SimpleNamespace(data=SimpleNamespace(files=["/mnt/user-data/workspace/app.py", "/mnt/user-data/workspace/node_modules/skip.py"])),
    )

    matches, truncated = sandbox.glob("/mnt/user-data/workspace", "**/*.py")

    assert matches == ["/mnt/user-data/workspace/app.py"]
    assert truncated is False


def test_aio_sandbox_grep_parses_json(monkeypatch) -> None:
    with patch("deerflow.community.aio_sandbox.aio_sandbox.AioSandboxClient"):
        sandbox = AioSandbox(id="test-sandbox", base_url="http://localhost:8080")
    monkeypatch.setattr(
        sandbox._client.file,
        "list_path",
        lambda **kwargs: SimpleNamespace(
            data=SimpleNamespace(
                files=[
                    SimpleNamespace(
                        name="app.py",
                        path="/mnt/user-data/workspace/app.py",
                        is_directory=False,
                    )
                ]
            )
        ),
    )
    monkeypatch.setattr(
        sandbox._client.file,
        "search_in_file",
        lambda **kwargs: SimpleNamespace(data=SimpleNamespace(line_numbers=[7], matches=["TODO = True"])),
    )

    matches, truncated = sandbox.grep("/mnt/user-data/workspace", "TODO")

    assert matches == [GrepMatch(path="/mnt/user-data/workspace/app.py", line_number=7, line="TODO = True")]
    assert truncated is False


def test_find_glob_matches_raises_not_a_directory(tmp_path) -> None:
    file_path = tmp_path / "file.txt"
    file_path.write_text("x\n", encoding="utf-8")

    try:
        find_glob_matches(file_path, "**/*.py")
        assert False, "Expected NotADirectoryError"
    except NotADirectoryError:
        pass


def test_find_grep_matches_raises_not_a_directory(tmp_path) -> None:
    file_path = tmp_path / "file.txt"
    file_path.write_text("TODO\n", encoding="utf-8")

    try:
        find_grep_matches(file_path, "TODO")
        assert False, "Expected NotADirectoryError"
    except NotADirectoryError:
        pass


def test_find_grep_matches_skips_symlink_outside_root(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("TODO outside\n", encoding="utf-8")
    (workspace / "outside-link.txt").symlink_to(outside)

    matches, truncated = find_grep_matches(workspace, "TODO")

    assert matches == []
    assert truncated is False


def test_glob_tool_honors_smaller_requested_max_results(tmp_path, monkeypatch) -> None:
    runtime = _make_runtime(tmp_path)
    workspace = tmp_path / "workspace"
    (workspace / "a.py").write_text("print('a')\n", encoding="utf-8")
    (workspace / "b.py").write_text("print('b')\n", encoding="utf-8")
    (workspace / "c.py").write_text("print('c')\n", encoding="utf-8")

    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: LocalSandbox(id="local"))
    monkeypatch.setattr(
        "deerflow.sandbox.tools.get_app_config",
        lambda: SimpleNamespace(get_tool_config=lambda name: SimpleNamespace(model_extra={"max_results": 50})),
    )

    result = glob_tool.func(
        runtime=runtime,
        description="limit glob matches",
        pattern="**/*.py",
        path="/mnt/user-data/workspace",
        max_results=2,
    )

    assert "Found 2 paths under /mnt/user-data/workspace (showing first 2)" in result
    assert "Results truncated." in result


def test_aio_sandbox_glob_include_dirs_enforces_root_boundary(monkeypatch) -> None:
    with patch("deerflow.community.aio_sandbox.aio_sandbox.AioSandboxClient"):
        sandbox = AioSandbox(id="test-sandbox", base_url="http://localhost:8080")
    monkeypatch.setattr(
        sandbox._client.file,
        "list_path",
        lambda **kwargs: SimpleNamespace(
            data=SimpleNamespace(
                files=[
                    SimpleNamespace(name="src", path="/mnt/workspace/src"),
                    SimpleNamespace(name="src2", path="/mnt/workspace2/src2"),
                ]
            )
        ),
    )

    matches, truncated = sandbox.glob("/mnt/workspace", "**", include_dirs=True)

    assert matches == ["/mnt/workspace/src"]
    assert truncated is False


def test_aio_sandbox_grep_skips_mismatched_line_number_payloads(monkeypatch) -> None:
    with patch("deerflow.community.aio_sandbox.aio_sandbox.AioSandboxClient"):
        sandbox = AioSandbox(id="test-sandbox", base_url="http://localhost:8080")
    monkeypatch.setattr(
        sandbox._client.file,
        "list_path",
        lambda **kwargs: SimpleNamespace(
            data=SimpleNamespace(
                files=[
                    SimpleNamespace(
                        name="app.py",
                        path="/mnt/user-data/workspace/app.py",
                        is_directory=False,
                    )
                ]
            )
        ),
    )
    monkeypatch.setattr(
        sandbox._client.file,
        "search_in_file",
        lambda **kwargs: SimpleNamespace(data=SimpleNamespace(line_numbers=[7], matches=["TODO = True", "extra"])),
    )

    matches, truncated = sandbox.grep("/mnt/user-data/workspace", "TODO")

    assert matches == [GrepMatch(path="/mnt/user-data/workspace/app.py", line_number=7, line="TODO = True")]
    assert truncated is False


# ---------------------------------------------------------------------------
# ls_tool — path masking
# ---------------------------------------------------------------------------


def test_ls_tool_masks_user_data_host_paths(tmp_path, monkeypatch) -> None:
    """ls_tool output must not leak host user-data paths; they should be virtual."""
    runtime = _make_runtime(tmp_path)
    workspace = tmp_path / "workspace"
    (workspace / "report.txt").write_text("hello\n", encoding="utf-8")
    (workspace / "subdir").mkdir()

    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: LocalSandbox(id="local"))

    result = ls_tool.func(
        runtime=runtime,
        description="list workspace",
        path="/mnt/user-data/workspace",
    )

    # Virtual paths must be present
    assert "/mnt/user-data/workspace" in result
    # Host paths must NOT leak
    assert str(workspace) not in result
    assert str(tmp_path) not in result


def test_ls_tool_masks_skills_host_paths(tmp_path, monkeypatch) -> None:
    """ls_tool output must not leak host skills paths; they should be virtual."""
    runtime = _make_runtime(tmp_path)
    skills_dir = tmp_path / "skills"
    (skills_dir / "public").mkdir(parents=True)
    (skills_dir / "public" / "SKILL.md").write_text("# Skill\n", encoding="utf-8")

    sandbox = LocalSandbox(
        id="local",
        path_mappings=[
            PathMapping(container_path="/mnt/skills", local_path=str(skills_dir), read_only=True),
        ],
    )
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: sandbox)

    result = ls_tool.func(
        runtime=runtime,
        description="list skills",
        path="/mnt/skills",
    )

    # Virtual paths must be present
    assert "/mnt/skills" in result
    # Host paths must NOT leak
    assert str(skills_dir) not in result
    assert str(tmp_path) not in result


def test_ls_tool_returns_empty_for_empty_directory(tmp_path, monkeypatch) -> None:
    """ls_tool should return '(empty)' for an empty directory."""
    runtime = _make_runtime(tmp_path)

    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: LocalSandbox(id="local"))

    result = ls_tool.func(
        runtime=runtime,
        description="list empty dir",
        path="/mnt/user-data/workspace",
    )

    assert result == "(empty)"


def test_ls_tool_skills_path_uses_sandbox_mapping_user_id_not_contextvar(tmp_path, monkeypatch) -> None:
    """ls_tool must resolve /mnt/skills/custom via the sandbox PathMapping
    (which uses the user_id from acquire time), not via _resolve_skills_path
    (which uses get_effective_user_id() from contextvar).

    Regression: when the contextvar user_id differs from the sandbox mapping's
    user_id (e.g., contextvar unset → "default", but sandbox uses authenticated
    "user-abc"), _resolve_skills_path would resolve to the wrong directory,
    making /mnt/skills/custom appear empty. The fix delegates resolution to the
    sandbox's PathMapping which always uses the acquire-time user_id.
    """
    from deerflow.runtime.user_context import reset_current_user, set_current_user

    # Create two user-specific custom skill directories:
    # - user-abc: has a skill "my-skill"
    # - default: empty (the fallback when contextvar is unset)
    base_dir = tmp_path / ".deer-flow"
    user_abc_custom = base_dir / "users" / "user-abc" / "skills" / "custom"
    user_abc_custom.mkdir(parents=True)
    (user_abc_custom / "my-skill").mkdir()
    (user_abc_custom / "my-skill" / "SKILL.md").write_text("# My Skill\n", encoding="utf-8")

    default_custom = base_dir / "users" / "default" / "skills" / "custom"
    default_custom.mkdir(parents=True)  # exists but empty

    # Create a sandbox with PathMappings that use user-abc's directory
    # (simulating a sandbox acquired for user-abc)
    sandbox = LocalSandbox(
        id="local:user-abc:thread-1",
        path_mappings=[
            PathMapping(container_path="/mnt/skills/custom", local_path=str(user_abc_custom), read_only=True),
        ],
    )
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: sandbox)

    # Listing a category root descends into the skills below it, so the
    # disabled-skill gate now resolves each one's enabled state. That lookup
    # needs app config; without it the gate fails closed (see PR #3889) and the
    # listing would be empty for a reason unrelated to what this test asserts.
    skills_root = tmp_path / "skills"
    (skills_root / "custom").mkdir(parents=True)
    app_config = SimpleNamespace(
        skills=SimpleNamespace(
            get_skills_path=lambda: skills_root,
            container_path="/mnt/skills",
            use="deerflow.skills.storage.local_skill_storage:LocalSkillStorage",
        ),
        skill_evolution=SimpleNamespace(enabled=False),
    )

    # Leave contextvar unset → get_effective_user_id() returns "default"
    # Before the fix, _resolve_skills_path would resolve to default_custom (empty)
    # After the fix, the sandbox PathMapping resolves to user-abc_custom (has my-skill)
    token = set_current_user(SimpleNamespace(id="default"))  # contextvar says "default"
    try:
        with patch("deerflow.config.paths.get_paths", return_value=Paths(base_dir=base_dir)):
            with patch("deerflow.config.get_app_config", return_value=app_config):
                result = ls_tool.func(
                    runtime=_make_runtime(tmp_path),
                    description="list custom skills",
                    path="/mnt/skills/custom",
                )

        # Must show user-abc's skill (sandbox mapping), NOT default's empty dir (contextvar)
        assert "my-skill" in result
        assert str(user_abc_custom) not in result  # host paths must not leak
    finally:
        reset_current_user(token)


def test_ls_tool_filters_upload_staging_files(tmp_path, monkeypatch) -> None:
    runtime = _make_runtime(tmp_path)
    uploads = tmp_path / "uploads"
    (uploads / "report.txt").write_text("ready\n", encoding="utf-8")
    (uploads / ".upload-active.part").write_text("partial\n", encoding="utf-8")
    (uploads / ".upload-note.txt").write_text("intentional\n", encoding="utf-8")

    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: LocalSandbox(id="local"))

    result = ls_tool.func(
        runtime=runtime,
        description="list uploads",
        path="/mnt/user-data/uploads",
    )

    assert "/mnt/user-data/uploads/report.txt" in result
    assert "/mnt/user-data/uploads/.upload-note.txt" in result
    assert ".upload-active.part" not in result


def _make_skills_sandbox(tmp_path, monkeypatch, *, disabled: str):
    """Skills tree with one disabled and one enabled public skill.

    Drives the real `_is_disabled_skill_path` gate through a real
    extensions_config.json rather than stubbing the gate out.
    """
    skills_dir = tmp_path / "skills"
    for name, body in [(disabled, "SECRET_PROCEDURE = step-1-step-2\n"), ("open-skill", "PUBLIC_PROCEDURE = hello\n")]:
        (skills_dir / "public" / name).mkdir(parents=True)
        (skills_dir / "public" / name / "SKILL.md").write_text(f"---\nname: {name}\n---\n\n{body}", encoding="utf-8")

    ext = tmp_path / "extensions_config.json"
    ext.write_text(
        json.dumps({"mcpServers": {}, "skills": {disabled: {"enabled": False}, "open-skill": {"enabled": True}}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(ext))

    sandbox = LocalSandbox(
        id="local",
        path_mappings=[PathMapping(container_path="/mnt/skills", local_path=str(skills_dir), read_only=True)],
    )
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: sandbox)
    return sandbox


def test_glob_tool_blocks_disabled_skill_root(tmp_path, monkeypatch) -> None:
    """glob must refuse a disabled skill's own directory, like ls and read_file do."""
    runtime = _make_runtime(tmp_path)
    _make_skills_sandbox(tmp_path, monkeypatch, disabled="secret-skill")

    result = glob_tool.func(
        runtime=runtime,
        description="list skill files",
        pattern="**/*.md",
        path="/mnt/skills/public/secret-skill",
    )

    assert "Skill 'secret-skill' is disabled" in result
    assert "SKILL.md" not in result


def test_grep_tool_blocks_disabled_skill_root(tmp_path, monkeypatch) -> None:
    """grep must refuse a disabled skill's own directory, like ls and read_file do."""
    runtime = _make_runtime(tmp_path)
    _make_skills_sandbox(tmp_path, monkeypatch, disabled="secret-skill")

    result = grep_tool.func(
        runtime=runtime,
        description="search skill files",
        pattern="SECRET_PROCEDURE",
        path="/mnt/skills/public/secret-skill",
    )

    assert "Skill 'secret-skill' is disabled" in result
    assert "SECRET_PROCEDURE = step-1-step-2" not in result


def test_glob_tool_does_not_surface_disabled_skill_from_ancestor_root(tmp_path, monkeypatch) -> None:
    """A root above the skill must not surface it: glob descends past the path gate."""
    runtime = _make_runtime(tmp_path)
    _make_skills_sandbox(tmp_path, monkeypatch, disabled="secret-skill")

    result = glob_tool.func(
        runtime=runtime,
        description="find skills",
        pattern="**/SKILL.md",
        path="/mnt/skills",
    )

    assert "secret-skill" not in result
    # ...while the enabled sibling is still returned.
    assert "/mnt/skills/public/open-skill/SKILL.md" in result


def test_grep_tool_does_not_surface_disabled_skill_content_from_ancestor_root(tmp_path, monkeypatch) -> None:
    """The strongest leak: grep from /mnt/skills printed a disabled skill's file contents."""
    runtime = _make_runtime(tmp_path)
    _make_skills_sandbox(tmp_path, monkeypatch, disabled="secret-skill")

    result = grep_tool.func(
        runtime=runtime,
        description="search skills",
        pattern="PROCEDURE",
        path="/mnt/skills",
    )

    assert "SECRET_PROCEDURE = step-1-step-2" not in result
    assert "secret-skill" not in result
    # ...while the enabled sibling still matches.
    assert "PUBLIC_PROCEDURE = hello" in result


def test_ls_tool_does_not_surface_disabled_skill_from_category_root(tmp_path, monkeypatch) -> None:
    """ls gates the requested path but descends two levels, so the category root leaked."""
    runtime = _make_runtime(tmp_path)
    _make_skills_sandbox(tmp_path, monkeypatch, disabled="secret-skill")

    result = ls_tool.func(
        runtime=runtime,
        description="list public skills",
        path="/mnt/skills/public",
    )

    assert "secret-skill" not in result
    # ...while the enabled sibling is still listed.
    assert "open-skill" in result


def test_ls_tool_keeps_category_dirs_when_listing_skills_root(tmp_path, monkeypatch) -> None:
    """`ls /mnt/skills` lists dirs with a trailing slash ("public/"), which the
    skill-name extractor must read as a category root, not as a skill named "".

    An empty name skips the `skill_name is None` short-circuit and falls through
    to a config read; it currently lands on "keep" only because unknown skills
    default to enabled. This pins the intended outcome directly: category dirs
    stay visible while the disabled skill below them does not.
    """
    runtime = _make_runtime(tmp_path)
    _make_skills_sandbox(tmp_path, monkeypatch, disabled="secret-skill")

    result = ls_tool.func(
        runtime=runtime,
        description="list skills root",
        path="/mnt/skills",
    )

    assert "/mnt/skills/public" in result
    assert "open-skill" in result
    assert "secret-skill" not in result


def test_extract_skill_name_treats_category_dir_with_trailing_slash_as_root() -> None:
    """LocalSandbox.list_dir appends "/" to directories, so the gate sees
    "/mnt/skills/public/" — which must resolve to None (category root), not "".
    """
    from deerflow.sandbox.tools import _extract_skill_name_from_skills_path as extract

    # Changed direction: trailing-slash category roots used to yield "".
    assert extract("/mnt/skills/public/") is None
    assert extract("/mnt/skills/custom/") is None
    assert extract("/mnt/skills/legacy/") is None
    # Unchanged directions: real skills still resolve, with or without the slash.
    assert extract("/mnt/skills/public") is None
    assert extract("/mnt/skills/public/bootstrap") == "bootstrap"
    assert extract("/mnt/skills/public/bootstrap/") == "bootstrap"
    assert extract("/mnt/skills/public/bootstrap/SKILL.md") == "bootstrap"
    assert extract("/mnt/skills/my-skill/") == "my-skill"
    assert extract("/mnt/user-data/workspace/file.md") is None


def _make_custom_skills_sandbox(tmp_path, monkeypatch, *, user_id: str, disabled: str):
    """Per-user CUSTOM skills tree with one disabled and one enabled skill.

    CUSTOM/LEGACY enabled state lives in the per-user ``_skill_states.json``
    (``UserScopedSkillStorage``), a different store from the public skills'
    ``extensions_config.json`` — so the public fixture above does not exercise
    this branch of ``_is_disabled_skill_path``.
    """
    from deerflow.skills.storage import reset_skill_storage

    base_dir = tmp_path / ".deer-flow"
    user_skills = base_dir / "users" / user_id / "skills"
    user_custom = user_skills / "custom"
    for name, body in [(disabled, "SECRET_PROCEDURE = step-1-step-2\n"), ("open-custom", "PUBLIC_PROCEDURE = hello\n")]:
        (user_custom / name).mkdir(parents=True)
        (user_custom / name / "SKILL.md").write_text(f"---\nname: {name}\n---\n\n{body}", encoding="utf-8")

    (user_skills / "_skill_states.json").write_text(
        json.dumps({disabled: {"enabled": False}, "open-custom": {"enabled": True}}),
        encoding="utf-8",
    )

    skills_root = tmp_path / "skills"
    (skills_root / "public").mkdir(parents=True)
    (skills_root / "custom").mkdir(parents=True)
    app_config = SimpleNamespace(
        skills=SimpleNamespace(
            get_skills_path=lambda: skills_root,
            container_path="/mnt/skills",
            use="deerflow.skills.storage.local_skill_storage:LocalSkillStorage",
        ),
        skill_evolution=SimpleNamespace(enabled=False),
    )

    sandbox = LocalSandbox(
        id=f"local:{user_id}:thread-1",
        path_mappings=[PathMapping(container_path="/mnt/skills/custom", local_path=str(user_custom), read_only=True)],
    )
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: sandbox)
    # The storage cache is keyed by user id, not by base_dir: a cached instance
    # from another test would read the wrong _skill_states.json.
    reset_skill_storage()
    monkeypatch.setattr("deerflow.sandbox.tools.resolve_runtime_user_id", lambda runtime: user_id)
    return base_dir, app_config


def test_grep_tool_does_not_surface_disabled_custom_skill(tmp_path, monkeypatch) -> None:
    """CUSTOM skills resolve enabled state through the per-user _skill_states.json,
    not extensions_config.json — the store the public-skill tests never touch."""
    from deerflow.skills.storage import reset_skill_storage

    runtime = _make_runtime(tmp_path)
    base_dir, app_config = _make_custom_skills_sandbox(tmp_path, monkeypatch, user_id="user-abc", disabled="secret-custom")

    try:
        with patch("deerflow.config.paths.get_paths", return_value=Paths(base_dir=base_dir)):
            with patch("deerflow.config.get_app_config", return_value=app_config):
                result = grep_tool.func(
                    runtime=runtime,
                    description="search custom skills",
                    pattern="PROCEDURE",
                    path="/mnt/skills/custom",
                )
    finally:
        reset_skill_storage()

    assert "SECRET_PROCEDURE = step-1-step-2" not in result
    assert "secret-custom" not in result
    # ...while the enabled sibling still matches.
    assert "PUBLIC_PROCEDURE = hello" in result


def test_ls_tool_does_not_surface_disabled_custom_skill(tmp_path, monkeypatch) -> None:
    """Same per-user store, via the descending ls listing."""
    from deerflow.skills.storage import reset_skill_storage

    runtime = _make_runtime(tmp_path)
    base_dir, app_config = _make_custom_skills_sandbox(tmp_path, monkeypatch, user_id="user-abc", disabled="secret-custom")

    try:
        with patch("deerflow.config.paths.get_paths", return_value=Paths(base_dir=base_dir)):
            with patch("deerflow.config.get_app_config", return_value=app_config):
                result = ls_tool.func(
                    runtime=runtime,
                    description="list custom skills",
                    path="/mnt/skills/custom",
                )
    finally:
        reset_skill_storage()

    assert "secret-custom" not in result
    assert "open-custom" in result
