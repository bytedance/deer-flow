"""Search the default provider's category-only skill mounts through public tools."""

import errno
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from deerflow.config import paths as paths_module
from deerflow.config.app_config import AppConfig
from deerflow.config.extensions_config import ExtensionsConfig, SkillStateConfig
from deerflow.sandbox import tools
from deerflow.sandbox.local.local_sandbox import LocalSandbox, PathMapping
from deerflow.sandbox.local.local_sandbox_provider import LocalSandboxProvider


def _write_skill(root, name):
    target = root / name / "SKILL.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"---\nname: {name}\ndescription: Search regression fixture\n---\nNEEDLE {name}\n", encoding="utf-8")


@pytest.fixture
def skill_search(tmp_path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(paths_module, "_paths", None)
    source = tmp_path / "skills"
    for name in ("alpha", "beta", "disabled"):
        _write_skill(source / "public", name)
    config = AppConfig.model_validate({"skills": {"path": str(source)}, "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}})
    extensions = ExtensionsConfig(skills={"disabled": SkillStateConfig(enabled=False)})
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: config)
    monkeypatch.setattr("deerflow.config.app_config.get_app_config", lambda: config)
    monkeypatch.setattr("deerflow.config.extensions_config.get_extensions_config", lambda: extensions)
    monkeypatch.setattr(ExtensionsConfig, "from_file", lambda *args, **kwargs: extensions)
    paths = paths_module.get_paths()
    for user in ("alice", "bob"):
        _write_skill(paths.user_custom_skills_dir(user), f"{user}-only")
    provider = LocalSandboxProvider()
    sandboxes = {user: provider.get(provider.acquire("shared-thread", user_id=user)) for user in ("alice", "bob")}
    monkeypatch.setattr(tools, "ensure_sandbox_initialized", lambda runtime: sandboxes[runtime.context["user_id"]])

    def runtime(user="alice"):
        return SimpleNamespace(
            context={"thread_id": "shared-thread", "user_id": user},
            config={},
            state={
                "sandbox": {"sandbox_id": sandboxes[user].id},
                "thread_data": {
                    "workspace_path": str(paths.sandbox_work_dir("shared-thread", user_id=user)),
                    "uploads_path": str(paths.sandbox_uploads_dir("shared-thread", user_id=user)),
                    "outputs_path": str(paths.sandbox_outputs_dir("shared-thread", user_id=user)),
                },
            },
        )

    return SimpleNamespace(sandboxes=sandboxes, runtime=runtime, paths=paths)


@pytest.mark.parametrize("tool_name", ["glob", "grep"])
def test_public_search_of_category_only_root_preserves_visibility(skill_search, tool_name):
    sandbox = skill_search.sandboxes["alice"]
    assert "/mnt/skills" not in {m.container_path for m in sandbox.path_mappings}
    assert "/mnt/skills/public/" in tools.ls_tool.func(runtime=skill_search.runtime(), path="/mnt/skills")
    tool = tools.glob_tool if tool_name == "glob" else tools.grep_tool
    pattern = "**/SKILL.md" if tool_name == "glob" else "NEEDLE"
    for user, other in (("alice", "bob"), ("bob", "alice")):
        result = tool.func(runtime=skill_search.runtime(user), path="/mnt/skills", pattern=pattern)
        for name in ("alpha", "beta", f"{user}-only"):
            assert f"/{name}/SKILL.md" in result
        assert f"{other}-only" not in result
        assert "disabled" not in result
        assert str(skill_search.paths.base_dir) not in result


@pytest.mark.parametrize("pattern", ["public/**/*.md", "*/alpha/*.md", "**/SKILL.md"])
def test_glob_pattern_is_relative_to_aggregate_root(skill_search, pattern):
    matches, truncated = skill_search.sandboxes["alice"].glob("/mnt/skills", pattern)
    assert "/mnt/skills/public/alpha/SKILL.md" in matches
    if pattern.startswith("public/"):
        assert all(path.startswith("/mnt/skills/public/") for path in matches)
    if "alpha" in pattern:
        assert matches == ["/mnt/skills/public/alpha/SKILL.md"]
    assert not truncated


def test_grep_glob_is_relative_to_aggregate_root(skill_search):
    matches, truncated = skill_search.sandboxes["alice"].grep("/mnt/skills", "NEEDLE", glob="custom/**/*.md", literal=True)
    assert [match.path for match in matches] == ["/mnt/skills/custom/alice-only/SKILL.md"]
    assert not truncated


def test_glob_can_match_category_directories(skill_search):
    sandbox = skill_search.sandboxes["alice"]
    assert sandbox.glob("/mnt/skills", "public", include_dirs=True) == (["/mnt/skills/public"], False)
    assert sandbox.glob("/mnt/skills", "public") == ([], False)


@pytest.mark.parametrize("method", ["glob", "grep"])
@pytest.mark.parametrize("limit", [1, 2, 3, 10])
def test_search_has_one_budget_across_category_mounts(skill_search, method, limit):
    sandbox = skill_search.sandboxes["alice"]
    pattern = "**/SKILL.md" if method == "glob" else "NEEDLE"
    matches, truncated = getattr(sandbox, method)("/mnt/skills", pattern, max_results=limit)
    assert len(matches) == min(limit, 3)
    assert truncated is (limit < 3)


@pytest.mark.parametrize("method", ["glob", "grep"])
def test_category_search_missing_paths_and_no_matches_are_unchanged(skill_search, method):
    search = getattr(skill_search.sandboxes["alice"], method)
    pattern = "SKILL.md" if method == "glob" else "NEEDLE"
    matches, _ = search("/mnt/skills/public", pattern)
    assert len(matches) == 2
    assert search("/mnt/skills", "NEVER_PRESENT_9381") == ([], False)
    with pytest.raises(FileNotFoundError):
        search("/mnt/skills/missing", pattern)


@pytest.mark.parametrize("method", ["glob", "grep"])
def test_public_search_still_refuses_user_data_root(skill_search, method):
    tool = tools.glob_tool if method == "glob" else tools.grep_tool
    result = tool.func(runtime=skill_search.runtime(), path="/mnt/user-data", pattern="*")
    assert result.startswith("Error:")


@pytest.mark.parametrize("method", ["glob", "grep"])
def test_aggregate_mapping_keeps_its_existing_search_path(tmp_path, method):
    _write_skill(tmp_path / "public", "allowed")
    sandbox = LocalSandbox("local:scoped", path_mappings=[PathMapping("/mnt/skills", str(tmp_path), read_only=True)])
    pattern = "**/SKILL.md" if method == "glob" else "NEEDLE"
    matches, _ = getattr(sandbox, method)("/mnt/skills", pattern)
    result_paths = matches if method == "glob" else [match.path for match in matches]
    assert result_paths == ["/mnt/skills/public/allowed/SKILL.md"]
    with pytest.raises(OSError):
        sandbox.write_file("/mnt/skills/public/allowed/SKILL.md", "replacement")


@pytest.mark.parametrize("method", ["glob", "grep"])
def test_virtual_parent_search_does_not_walk_unmounted_host_files(tmp_path, method):
    parent = tmp_path / "virtual-parent"
    parent.mkdir()
    (parent / "unmounted.md").write_text("NEEDLE private host file", encoding="utf-8")
    mounted = tmp_path / "mounted"
    _write_skill(mounted, "allowed")
    virtual = parent.as_posix()
    sandbox = LocalSandbox("local:overlay", path_mappings=[PathMapping(f"{virtual}/public", str(mounted), read_only=True)])
    pattern = "**/*.md" if method == "glob" else "NEEDLE"
    matches, _ = getattr(sandbox, method)(virtual, pattern)
    result_paths = matches if method == "glob" else [match.path for match in matches]
    assert result_paths == [f"{virtual}/public/allowed/SKILL.md"]


@pytest.mark.parametrize("method", ["glob", "grep"])
def test_search_does_not_write_through_readonly_category_mounts(skill_search, method):
    sandbox = skill_search.sandboxes["alice"]
    pattern = "**/SKILL.md" if method == "glob" else "NEEDLE"
    getattr(sandbox, method)("/mnt/skills", pattern)
    with pytest.raises(OSError):
        sandbox.write_file("/mnt/skills/public/alpha/SKILL.md", "replacement")


@pytest.mark.parametrize("method", ["glob", "grep"])
def test_configured_virtual_root_and_empty_mounts(tmp_path, method):
    mounted = tmp_path / "public"
    mounted.mkdir()
    sandbox = LocalSandbox("local:configured", path_mappings=[PathMapping("/opt/team-skills/public", str(mounted), read_only=True)])
    search = getattr(sandbox, method)
    pattern = "**/SKILL.md" if method == "glob" else "NEEDLE"
    assert search("/opt/team-skills", pattern) == ([], False)
    _write_skill(mounted, "allowed")
    matches, _ = search("/opt/team-skills/", pattern)
    result_paths = matches if method == "glob" else [match.path for match in matches]
    assert result_paths == ["/opt/team-skills/public/allowed/SKILL.md"]


@pytest.mark.parametrize("method", ["glob", "grep"])
def test_search_errors_keep_virtual_paths(skill_search, monkeypatch, method):
    def denied(root, *args, **kwargs):
        raise PermissionError(errno.EACCES, "Permission denied", str(root / "blocked"))

    name = "find_glob_matches" if method == "glob" else "find_grep_matches"
    monkeypatch.setattr(f"deerflow.sandbox.local.local_sandbox.{name}", denied)
    with pytest.raises(PermissionError) as caught:
        getattr(skill_search.sandboxes["alice"], method)("/mnt/skills", "*")
    assert caught.value.filename.startswith("/mnt/skills/")
    assert str(skill_search.paths.base_dir) not in str(caught.value)


@pytest.mark.parametrize("method", ["glob", "grep"])
def test_existing_file_is_not_treated_as_a_virtual_parent(tmp_path, method):
    parent = tmp_path / "not-a-directory"
    parent.write_text("host file", encoding="utf-8")
    mounted = tmp_path / "public"
    mounted.mkdir()
    virtual = parent.as_posix()
    sandbox = LocalSandbox("local:invalid-parent", path_mappings=[PathMapping(f"{virtual}/public", str(mounted), read_only=True)])
    with pytest.raises(NotADirectoryError):
        getattr(sandbox, method)(virtual, "*")


@pytest.mark.parametrize("method", ["glob", "grep"])
def test_missing_mount_cannot_fall_back_to_unmounted_host_files(tmp_path, method):
    parent = tmp_path / "virtual-parent"
    parent.mkdir()
    (parent / "unmounted.md").write_text("NEEDLE private host file", encoding="utf-8")
    virtual = parent.as_posix()
    sandbox = LocalSandbox("local:missing-mount", path_mappings=[PathMapping(f"{virtual}/public", str(tmp_path / "missing"), read_only=True)])
    with pytest.raises(FileNotFoundError):
        getattr(sandbox, method)(virtual, "*")


@pytest.mark.parametrize("method", ["glob", "grep"])
@pytest.mark.parametrize("mount_name", ["node_modules", "build", "dist", "out", "logs", "env", "target"])
def test_explicit_mount_with_ignored_name_is_searchable(tmp_path, method, mount_name):
    parent = tmp_path / "virtual-parent"
    parent.mkdir()
    (parent / "unmounted.md").write_text("NEEDLE private host file", encoding="utf-8")
    mounted = tmp_path / "mounted"
    _write_skill(mounted, "allowed")
    _write_skill(mounted / "node_modules", "hidden")
    (mounted / "ignored.log").write_text("NEEDLE ignored file", encoding="utf-8")
    virtual = parent.as_posix()
    mount_path = f"{virtual}/{mount_name}"
    sandbox = LocalSandbox("local:explicit-mount", path_mappings=[PathMapping(mount_path, str(mounted), read_only=True)])
    expected = [f"{mount_path}/allowed/SKILL.md"]
    assert f"{mount_path}/" in sandbox.list_dir(virtual)
    assert "NEEDLE allowed" in sandbox.read_file(expected[0])

    pattern = "**/*" if method == "glob" else "NEEDLE"
    matches, truncated = getattr(sandbox, method)(virtual, pattern)
    result_paths = matches if method == "glob" else [match.path for match in matches]
    assert result_paths == expected
    assert not truncated
    root_pattern = f"{mount_name}/**/SKILL.md"
    if method == "glob":
        assert sandbox.glob(virtual, root_pattern) == (expected, False)
        assert sandbox.glob(virtual, mount_name, include_dirs=True) == ([mount_path], False)
    else:
        matches, truncated = sandbox.grep(virtual, "NEEDLE", glob=root_pattern)
        assert [match.path for match in matches] == expected
        assert not truncated


@pytest.mark.parametrize("method", ["glob", "grep"])
@pytest.mark.parametrize("mount_state", ["missing", "file"])
def test_broken_mount_warns_with_its_virtual_category(skill_search, caplog, method, mount_state):
    sandbox = skill_search.sandboxes["alice"]
    mapping = next(mapping for mapping in sandbox.path_mappings if mapping.container_path == "/mnt/skills/public")
    root = Path(mapping.local_path)
    root.rename(root.with_name("public-backup"))
    if mount_state == "file":
        root.write_text("not a directory", encoding="utf-8")
    tool = tools.glob_tool if method == "glob" else tools.grep_tool
    pattern = "**/SKILL.md" if method == "glob" else "NEEDLE"
    with caplog.at_level(logging.WARNING, logger="deerflow.sandbox.local.local_sandbox"):
        result = tool.func(runtime=skill_search.runtime(), path="/mnt/skills", pattern=pattern)
    expected_error = "Directory not found" if mount_state == "missing" else "Path is not a directory"
    assert result == f"Error: {expected_error}: /mnt/skills"
    warnings = [record for record in caplog.records if record.name == "deerflow.sandbox.local.local_sandbox" and record.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert mapping.container_path in warnings[0].getMessage()
    assert str(root) not in result
