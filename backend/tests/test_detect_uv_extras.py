"""Unit tests for scripts/detect_uv_extras.py.

The detector resolves uv extras for `make dev` so that postgres (and any
future opt-in extras) are not wiped on every restart — see Issue #2754.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DETECT_SCRIPT_PATH = REPO_ROOT / "scripts" / "detect_uv_extras.py"


spec = importlib.util.spec_from_file_location("deerflow_detect_uv_extras", DETECT_SCRIPT_PATH)
assert spec is not None and spec.loader is not None
detect = importlib.util.module_from_spec(spec)
spec.loader.exec_module(detect)


@pytest.fixture
def isolated_cwd(tmp_path, monkeypatch):
    """Isolate `find_config_file()` from the real repo by chdir + clearing env."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("UV_EXTRAS", raising=False)
    monkeypatch.delenv("DEER_FLOW_CONFIG_PATH", raising=False)
    return tmp_path


def test_parse_env_extras_supports_comma_and_whitespace():
    assert detect.parse_env_extras("postgres") == ["postgres"]
    assert detect.parse_env_extras("postgres,ollama") == ["postgres", "ollama"]
    assert detect.parse_env_extras("postgres ollama") == ["postgres", "ollama"]
    assert detect.parse_env_extras(" postgres ,  ollama ,") == ["postgres", "ollama"]
    assert detect.parse_env_extras("") == []


def test_parse_env_extras_drops_shell_metacharacters(capsys):
    """A `.env` value containing shell injection bait must not pass through.

    The whitelist guarantees the *bytes* that reach `uv sync` cannot include
    shell metacharacters. Any name that looks identifier-like still survives
    (uv itself will reject unknown extras with its own error), but `;`, `&`,
    backticks, parentheses, slashes, etc. are stripped.
    """
    # Pure-metacharacter inputs collapse to empty.
    assert detect.parse_env_extras(";") == []
    assert detect.parse_env_extras("$(whoami)") == []
    assert detect.parse_env_extras("`echo bad`") == []
    assert detect.parse_env_extras("postgres;evil") == []  # single token, contains `;`
    # Splitting on whitespace yields ['rm'] which is identifier-shaped, but the
    # destructive bits (`;`, `-rf`, `/`) are dropped.
    assert detect.parse_env_extras("; rm -rf /") == ["rm"]
    err = capsys.readouterr().err
    assert "ignoring invalid UV_EXTRAS entry" in err
    assert "';'" in err  # confirms the dangerous token was reported and dropped


def test_parse_env_extras_rejects_leading_digits_and_punctuation():
    """Names must start with a letter — pyproject extras follow this shape."""
    assert detect.parse_env_extras("1postgres") == []
    assert detect.parse_env_extras("-postgres") == []
    # Hyphens and underscores inside the name are fine.
    assert detect.parse_env_extras("post_gres") == ["post_gres"]
    assert detect.parse_env_extras("post-gres") == ["post-gres"]


def test_format_flags_emits_one_flag_per_extra():
    assert detect.format_flags([]) == ""
    assert detect.format_flags(["postgres"]) == "--extra postgres"
    assert detect.format_flags(["postgres", "ollama"]) == "--extra postgres --extra ollama"


def test_strip_comment_preserves_quoted_hash():
    assert detect._strip_comment("backend: postgres  # trailing") == "backend: postgres"
    assert detect._strip_comment('name: "value#with-hash"') == 'name: "value#with-hash"'
    assert detect._strip_comment("# whole line comment") == ""


def test_section_value_finds_nested_key():
    yaml_lines = [
        "database:",
        "  backend: postgres",
        "  postgres_url: $DATABASE_URL",
        "",
        "checkpointer:",
        "  type: sqlite",
    ]
    assert detect.section_value(yaml_lines, "database", "backend") == "postgres"
    assert detect.section_value(yaml_lines, "checkpointer", "type") == "sqlite"
    assert detect.section_value(yaml_lines, "database", "missing") is None
    assert detect.section_value(yaml_lines, "absent_section", "anything") is None


def test_section_value_ignores_commented_lines():
    yaml_lines = [
        "# database:",
        "#   backend: postgres",
        "database:",
        "  backend: sqlite",
    ]
    assert detect.section_value(yaml_lines, "database", "backend") == "sqlite"


def test_section_value_strips_quotes():
    yaml_lines = [
        "database:",
        '  backend: "postgres"',
    ]
    assert detect.section_value(yaml_lines, "database", "backend") == "postgres"


def test_section_value_does_not_descend_into_grandchildren():
    yaml_lines = [
        "database:",
        "  backend: sqlite",
        "  nested:",
        "    backend: postgres",
    ]
    # Only the immediate child level counts — keeps the parser predictable.
    assert detect.section_value(yaml_lines, "database", "backend") == "sqlite"


def test_detect_from_config_postgres_via_database(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("database:\n  backend: postgres\n  postgres_url: $DATABASE_URL\n")
    assert detect.detect_from_config(cfg) == ["postgres"]


def test_detect_from_config_postgres_via_checkpointer(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("checkpointer:\n  type: postgres\n  connection_string: postgresql://localhost/db\n")
    assert detect.detect_from_config(cfg) == ["postgres"]


def test_detect_from_config_sqlite_returns_no_extras(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("database:\n  backend: sqlite\n  sqlite_dir: .deer-flow/data\n")
    assert detect.detect_from_config(cfg) == []


def test_detect_from_config_dedupes_when_both_present(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("checkpointer:\n  type: postgres\ndatabase:\n  backend: postgres\n")
    # Sorted unique extras, no double-counting.
    assert detect.detect_from_config(cfg) == ["postgres"]


def test_detect_from_config_missing_file_returns_empty(tmp_path):
    assert detect.detect_from_config(tmp_path / "does-not-exist.yaml") == []


def test_resolve_extras_env_overrides_config(isolated_cwd, monkeypatch):
    cfg = isolated_cwd / "config.yaml"
    cfg.write_text("database:\n  backend: sqlite\n")
    monkeypatch.setenv("UV_EXTRAS", "postgres")

    assert detect.resolve_extras() == ["postgres"]


def test_resolve_extras_env_supports_multiple(isolated_cwd, monkeypatch):
    monkeypatch.setenv("UV_EXTRAS", "postgres,ollama")
    assert detect.resolve_extras() == ["postgres", "ollama"]


def test_resolve_extras_falls_back_to_config(isolated_cwd):
    (isolated_cwd / "config.yaml").write_text("database:\n  backend: postgres\n")
    assert detect.resolve_extras() == ["postgres"]


def test_resolve_extras_respects_explicit_config_path(tmp_path, monkeypatch):
    monkeypatch.delenv("UV_EXTRAS", raising=False)
    elsewhere = tmp_path / "elsewhere.yaml"
    elsewhere.write_text("database:\n  backend: postgres\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(elsewhere))

    assert detect.resolve_extras() == ["postgres"]


def test_resolve_extras_no_config_no_env(isolated_cwd):
    assert detect.resolve_extras() == []


def test_resolve_extras_finds_backend_subdir_config(isolated_cwd):
    sub = isolated_cwd / "backend"
    sub.mkdir()
    (sub / "config.yaml").write_text("database:\n  backend: postgres\n")
    assert detect.resolve_extras() == ["postgres"]


def test_resolve_extras_root_config_takes_precedence(isolated_cwd):
    (isolated_cwd / "config.yaml").write_text("database:\n  backend: sqlite\n")
    sub = isolated_cwd / "backend"
    sub.mkdir()
    (sub / "config.yaml").write_text("database:\n  backend: postgres\n")
    # Root config.yaml is checked first, matching the precedence in serve.sh.
    assert detect.resolve_extras() == []
