"""`shell-env-dump` must report an environment dump, not a path or a shebang.

The rule's own message is "Shell script dumps the environment", so only a command
that actually dumps it counts. The word `env` also appears as a path component in
the portable shebang (`#!/usr/bin/env bash`, used by this repository's own
`skills/public/claude-to-deerflow/scripts/*.sh`), in host labels
(`https://env.example.com`), in dotted file names and in option names
(`--env`), as a plain command argument (`echo env`) and inside comments
(`# export -p`); none of them dumps anything, so the command word must sit at the
start of a command (line start or after a `;`, `&`, `|`, `(`, `)` or `{`).
"""

from __future__ import annotations

from pathlib import Path

from deerflow.skills.skillscan.orchestrator import scan_skill_dir


def _write_script(skill_dir: Path, body: str) -> None:
    scripts = skill_dir / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text("---\nname: demo\ndescription: A demo skill\n---\n\nBody.\n", encoding="utf-8")
    (scripts / "run.sh").write_text(body, encoding="utf-8")


def _rules(skill_dir: Path) -> set[str]:
    return {finding["rule_id"] for finding in scan_skill_dir(skill_dir)["findings"]}


def test_env_shebang_is_not_an_environment_dump(tmp_path: Path) -> None:
    """The portable shebang names a path, so it is not an `env` invocation."""
    _write_script(tmp_path, "#!/usr/bin/env bash\necho hello\n")
    assert "shell-env-dump" not in _rules(tmp_path)


def test_env_in_a_url_host_is_not_an_environment_dump(tmp_path: Path) -> None:
    """A host label that happens to read `env` is not an environment dump."""
    _write_script(tmp_path, "#!/bin/bash\ncurl https://env.example.com/x\n")
    assert "shell-env-dump" not in _rules(tmp_path)


def test_env_file_name_is_not_an_environment_dump(tmp_path: Path) -> None:
    """`source .env` loads one file; it does not dump the environment."""
    _write_script(tmp_path, "#!/bin/bash\nset -a\nsource .env\n")
    assert "shell-env-dump" not in _rules(tmp_path)


def test_env_option_name_is_not_an_environment_dump(tmp_path: Path) -> None:
    """`--env MODE=fast` sets one variable for one command; it is not a dump."""
    _write_script(tmp_path, "#!/bin/bash\ndocker run --env MODE=fast image\n")
    assert "shell-env-dump" not in _rules(tmp_path)


def test_bare_env_command_still_reports(tmp_path: Path) -> None:
    """A bare `env` is exactly the dump the rule exists for."""
    _write_script(tmp_path, "#!/bin/bash\nenv\n")
    assert "shell-env-dump" in _rules(tmp_path)


def test_printenv_command_still_reports(tmp_path: Path) -> None:
    _write_script(tmp_path, "#!/bin/bash\nprintenv | sort\n")
    assert "shell-env-dump" in _rules(tmp_path)


def test_export_p_still_reports(tmp_path: Path) -> None:
    _write_script(tmp_path, "#!/bin/bash\nexport -p\n")
    assert "shell-env-dump" in _rules(tmp_path)


def test_env_as_a_command_argument_is_not_an_environment_dump(tmp_path: Path) -> None:
    """`echo env` prints the word, not the environment: `env` is an argument here."""
    _write_script(tmp_path, "#!/bin/bash\necho env\n")
    assert "shell-env-dump" not in _rules(tmp_path)


def test_env_in_a_comment_is_not_an_environment_dump(tmp_path: Path) -> None:
    """Comment text is not a command, so `# env` dumps nothing."""
    _write_script(tmp_path, "#!/bin/bash\n# env\n")
    assert "shell-env-dump" not in _rules(tmp_path)


def test_export_p_in_a_comment_is_not_an_environment_dump(tmp_path: Path) -> None:
    """A commented `export -p` is documentation, not an invocation."""
    _write_script(tmp_path, "#!/bin/bash\n# export -p prints the environment\n")
    assert "shell-env-dump" not in _rules(tmp_path)


def test_env_after_a_command_separator_still_reports(tmp_path: Path) -> None:
    """`true; env` runs `env` as a second command on the line."""
    _write_script(tmp_path, "#!/bin/bash\ntrue; env\n")
    assert "shell-env-dump" in _rules(tmp_path)


def test_env_after_a_pipe_still_reports(tmp_path: Path) -> None:
    _write_script(tmp_path, "#!/bin/bash\ncat file | printenv\n")
    assert "shell-env-dump" in _rules(tmp_path)


def test_indented_env_still_reports(tmp_path: Path) -> None:
    """Indentation is not a command argument, so a line-leading `env` still dumps."""
    _write_script(tmp_path, "#!/bin/bash\n    env\n")
    assert "shell-env-dump" in _rules(tmp_path)


def test_env_after_an_assignment_prefix_still_reports(tmp_path: Path) -> None:
    """`FOO=1 env` runs `env`; the assignment is a prefix, not an argument."""
    _write_script(tmp_path, "#!/bin/bash\nFOO=1 env\n")
    assert "shell-env-dump" in _rules(tmp_path)
