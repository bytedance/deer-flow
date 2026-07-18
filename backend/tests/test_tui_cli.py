"""Tests for TUI launch-mode planning + arg parsing (pure, no Textual)."""

from deerflow.tui.cli import LaunchPlan, plan_launch


def plan(argv, *, stdin_tty=True, stdout_tty=True, env=None):
    return plan_launch(argv, stdin_isatty=stdin_tty, stdout_isatty=stdout_tty, env=env or {})


def test_bare_command_on_tty_launches_tui():
    p = plan([])
    assert p.mode == "tui"
    assert p.forced_tui is False


def test_non_tty_with_no_message_falls_back_to_headless_help():
    p = plan([], stdin_tty=False, stdout_tty=False)
    assert p.mode == "headless-help"
    assert p.reason


def test_print_with_message():
    p = plan(["--print", "summarize this repo"])
    assert p.mode == "print"
    assert p.message == "summarize this repo"
    assert p.read_stdin is False


def test_print_without_value_reads_stdin_when_piped():
    p = plan(["--print"], stdin_tty=False)
    assert p.mode == "print"
    assert p.read_stdin is True


def test_json_mode():
    p = plan(["--json", "hello"])
    assert p.mode == "json"
    assert p.message == "hello"


def test_force_tui_even_without_tty():
    p = plan(["--tui"], stdin_tty=False, stdout_tty=False)
    assert p.mode == "tui"
    assert p.forced_tui is True


def test_env_var_forces_tui():
    p = plan([], stdin_tty=False, stdout_tty=False, env={"DEER_FLOW_TUI": "1"})
    assert p.mode == "tui"


def test_cli_flag_with_message_runs_print():
    p = plan(["--cli", "do", "this", "thing"])
    assert p.mode == "print"
    assert p.message == "do this thing"


def test_cli_flag_without_message_is_headless_help():
    p = plan(["--cli"])
    assert p.mode == "headless-help"


def test_cli_continue_runs_headless_reading_stdin():
    p = plan(["--cli", "--continue"], stdin_tty=False)
    assert p.mode == "print"
    assert p.read_stdin is True
    assert p.continue_recent is True


def test_cli_with_piped_stdin_runs_headless():
    p = plan(["--cli"], stdin_tty=False)
    assert p.mode == "print"
    assert p.read_stdin is True


def test_continue_recent_flag():
    p = plan(["--continue"])
    assert p.mode == "tui"
    assert p.continue_recent is True


def test_resume_specific_thread():
    p = plan(["--resume", "thread-abc"])
    assert p.mode == "tui"
    assert p.thread_id == "thread-abc"


def test_chat_subcommand_is_accepted():
    p = plan(["chat"])
    assert p.mode == "tui"


def test_chat_subcommand_with_print():
    p = plan(["chat", "--print", "hi"])
    assert p.mode == "print"
    assert p.message == "hi"


def test_positional_message_becomes_initial_tui_prompt():
    p = plan(["explain", "the", "codebase"])
    assert p.mode == "tui"
    assert p.message == "explain the codebase"


def test_plan_is_a_launch_plan_instance():
    assert isinstance(plan([]), LaunchPlan)
