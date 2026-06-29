from deerflow.tui.command_registry import build_registry, resolve


def test_goal_is_builtin_command():
    resolved = resolve("/goal finish the implementation")

    assert resolved.kind == "builtin"
    assert resolved.name == "goal"
    assert resolved.args == "finish the implementation"


def test_goal_builtin_takes_precedence_over_skill():
    registry = build_registry([{"name": "goal", "description": "skill", "enabled": True}])

    assert [command.name for command in registry].count("goal") == 1
    assert resolve("/goal finish", skills=["goal"]).kind == "builtin"
