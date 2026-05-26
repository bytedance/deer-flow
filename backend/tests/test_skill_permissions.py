import stat

from deerflow.skills.permissions import make_skill_tree_sandbox_readable


def _mode(path):
    return stat.S_IMODE(path.stat().st_mode)


def test_skill_tree_readability_includes_hidden_paths_and_removes_sandbox_write(tmp_path):
    root = tmp_path / "demo-skill"
    hidden_dir = root / ".hidden"
    scripts_dir = root / "scripts"
    hidden_dir.mkdir(parents=True)
    scripts_dir.mkdir()
    env_file = root / ".env"
    hidden_file = hidden_dir / ".secret"
    script_file = scripts_dir / "run.sh"
    env_file.write_text("secret", encoding="utf-8")
    hidden_file.write_text("secret", encoding="utf-8")
    script_file.write_text("#!/bin/sh\n", encoding="utf-8")

    root.chmod(0o777)
    hidden_dir.chmod(0o777)
    scripts_dir.chmod(0o777)
    env_file.chmod(0o666)
    hidden_file.chmod(0o600)
    script_file.chmod(0o777)

    make_skill_tree_sandbox_readable(root)

    assert _mode(root) == 0o755
    assert _mode(hidden_dir) == 0o755
    assert _mode(scripts_dir) == 0o755
    assert _mode(env_file) == 0o644
    assert _mode(hidden_file) == 0o644
    assert _mode(script_file) == 0o755
