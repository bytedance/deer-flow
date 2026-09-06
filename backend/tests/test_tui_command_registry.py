"""Tests for the slash-command registry (pure)."""

from deerflow.tui.command_registry import (
    BUILTIN_COMMANDS,
    build_registry,
    filter_commands,
    format_command_help,
    resolve,
)


def _skills():
    return [
        {"name": "brainstorming", "description": "Explore ideas", "enabled": True},
        {"name": "tdd", "description": "Test driven dev", "enabled": True},
        {"name": "disabled-one", "description": "off", "enabled": False},
    ]


def test_build_registry_includes_all_builtins():
    registry = build_registry([])
    names = {c.name for c in registry}
    for builtin in BUILTIN_COMMANDS:
        assert builtin.name in names


def test_build_registry_adds_enabled_skill_commands_only():
    registry = build_registry(_skills())
    skill_names = {c.name for c in registry if c.category == "skill"}
    assert "brainstorming" in skill_names
    assert "tdd" in skill_names
    assert "disabled-one" not in skill_names


def test_filter_empty_query_returns_all():
    registry = build_registry([])
    assert filter_commands(registry, "") == registry


def test_filter_matches_name_substring_case_insensitive():
    registry = build_registry([])
    results = filter_commands(registry, "MOD")
    assert any(c.name == "model" for c in results)


def test_filter_matches_description():
    registry = build_registry(_skills())
    results = filter_commands(registry, "explore")
    assert any(c.name == "brainstorming" for c in results)


def test_filter_ranks_prefix_matches_before_substring():
    registry = build_registry([])
    results = filter_commands(registry, "me")
    # "memory" (prefix) should rank above a command that only contains "me"
    names = [c.name for c in results]
    assert "memory" in names
    assert names.index("memory") == 0


def test_resolve_plain_text_is_message():
    res = resolve("hello there")
    assert res.kind == "message"
    assert res.text == "hello there"


def test_resolve_builtin_command():
    res = resolve("/model")
    assert res.kind == "builtin"
    assert res.name == "model"


def test_resolve_builtin_with_args():
    res = resolve("/resume thread-123")
    assert res.kind == "builtin"
    assert res.name == "resume"
    assert res.args == "thread-123"


def test_resolve_skill_activation():
    res = resolve("/tdd write the test first", skills=["tdd"])
    assert res.kind == "skill"
    assert res.name == "tdd"
    assert res.args == "write the test first"


def test_resolve_unknown_command():
    res = resolve("/definitely-not-a-command", skills=["tdd"])
    assert res.kind == "unknown"
    assert res.name == "definitely-not-a-command"


def test_resolve_bare_slash_is_unknown_empty():
    res = resolve("/")
    assert res.kind == "unknown"


def test_goal_is_builtin_command():
    resolved = resolve("/goal finish the implementation")

    assert resolved.kind == "builtin"
    assert resolved.name == "goal"
    assert resolved.args == "finish the implementation"


def test_clear_is_builtin_command():
    resolved = resolve("/clear")

    assert resolved.kind == "builtin"
    assert resolved.name == "clear"
    assert resolved.args == ""


def test_goal_builtin_takes_precedence_over_skill():
    registry = build_registry([{"name": "goal", "description": "skill", "enabled": True}])

    assert [command.name for command in registry].count("goal") == 1
    assert resolve("/goal finish", skills=["goal"]).kind == "builtin"


# --------------------------------------------------------------------------- #
# /help text <-> registry parity
# --------------------------------------------------------------------------- #


def test_help_lists_every_builtin_command():
    help_line = format_command_help()
    # Every registered built-in must be advertised in /help; this is the guard
    # against the help text silently drifting from BUILTIN_COMMANDS.
    for command in BUILTIN_COMMANDS:
        assert f"/{command.name}" in help_line


def test_help_lists_only_builtin_commands():
    help_line = format_command_help()
    slugs = [token[1:] for token in help_line.split() if token.startswith("/")]
    assert set(slugs) == {command.name for command in BUILTIN_COMMANDS}


def test_help_preserves_registry_order():
    help_line = format_command_help()
    slugs = [token[1:] for token in help_line.split() if token.startswith("/")]
    assert slugs == [command.name for command in BUILTIN_COMMANDS]


def test_help_has_no_duplicate_commands():
    help_line = format_command_help()
    slugs = [token[1:] for token in help_line.split() if token.startswith("/")]
    assert len(slugs) == len(set(slugs))


def test_help_starts_with_commands_label():
    assert format_command_help().startswith("Commands:  /")
