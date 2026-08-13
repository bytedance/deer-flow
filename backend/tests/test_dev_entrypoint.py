"""Unit tests for docker/dev-entrypoint.sh (UV_EXTRAS validation + parsing).

Exercises the script via its `--print-extras` dry-run hook so we don't actually
launch uvicorn or hit /app/logs. Together with test_detect_uv_extras.py these
cover both the local make-dev path and the docker-compose-dev path with the
same shape — see PR #2767 / Issue #2754.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ENTRYPOINT = REPO_ROOT / "docker" / "dev-entrypoint.sh"


def _run(
    uv_extras: str | None,
    *,
    config_path: Path | None = None,
    stream_bridge_redis_url: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Invoke the entrypoint's public extras-resolution dry run."""
    env = os.environ.copy()
    env.pop("UV_EXTRAS", None)
    env.pop("DEER_FLOW_CONFIG_PATH", None)
    env.pop("DEER_FLOW_STREAM_BRIDGE_REDIS_URL", None)
    if uv_extras is not None:
        env["UV_EXTRAS"] = uv_extras
    if config_path is not None:
        env["DEER_FLOW_CONFIG_PATH"] = str(config_path)
    if stream_bridge_redis_url is not None:
        env["DEER_FLOW_STREAM_BRIDGE_REDIS_URL"] = stream_bridge_redis_url
    return subprocess.run(
        ["sh", str(ENTRYPOINT), "--print-extras"],
        cwd=ENTRYPOINT.parent,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_entrypoint_script_exists_and_is_posix_sh():
    assert ENTRYPOINT.is_file()
    # Catch syntax errors before runtime — `sh -n` is a parse-only check.
    proc = subprocess.run(["sh", "-n", str(ENTRYPOINT)], capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stderr


def test_entrypoint_excludes_runtime_state_from_uvicorn_reload():
    content = ENTRYPOINT.read_text(encoding="utf-8")

    assert ': "${DEER_FLOW_HOME:=/app/backend/.deer-flow}"' in content
    # sandbox must be created too, not just .deer-flow (#3459 / #3454).
    assert 'mkdir -p "$DEER_FLOW_HOME" /app/backend/.deer-flow /app/backend/sandbox' in content
    assert "--reload-include='*.yaml .env'" not in content
    assert "--reload-include='*.yaml'" in content
    assert "--reload-include='.env'" in content
    assert "--reload-exclude=/app/backend/sandbox" in content
    assert '--reload-exclude="$DEER_FLOW_HOME"' in content
    assert "--reload-exclude=/app/backend/.deer-flow" in content


def test_failed_sync_recreates_a_clean_virtual_environment():
    content = ENTRYPOINT.read_text(encoding="utf-8")

    assert "uv venv --clear .venv" in content
    assert "uv venv --allow-existing .venv" not in content


def test_no_uv_extras_yields_empty_flags():
    proc = _run(None)
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""


def test_no_explicit_extras_uses_the_runtime_selected_config(tmp_path: Path):
    config_path = tmp_path / "deployment.yaml"
    config_path.write_text(
        "database:\n  backend: postgres\ntools:\n  - name: browser_navigate\n",
        encoding="utf-8",
    )

    proc = _run(None, config_path=config_path)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "--extra browser --extra postgres"


def test_single_extra():
    proc = _run("postgres")
    assert proc.returncode == 0
    assert proc.stdout.strip() == "--extra postgres"


def test_multi_extra_comma_separated():
    proc = _run("postgres,ollama")
    assert proc.returncode == 0
    assert proc.stdout.strip() == "--extra postgres --extra ollama"


def test_multi_extra_whitespace_separated():
    proc = _run("postgres ollama")
    assert proc.returncode == 0
    assert proc.stdout.strip() == "--extra postgres --extra ollama"


def test_multi_extra_mixed_separators():
    proc = _run(" postgres ,  ollama ,")
    assert proc.returncode == 0
    assert proc.stdout.strip() == "--extra postgres --extra ollama"


def test_explicit_extras_override_config_and_are_deduplicated(tmp_path: Path):
    config_path = tmp_path / "deployment.yaml"
    config_path.write_text("database:\n  backend: postgres\n", encoding="utf-8")

    proc = _run("redis,redis browser redis", config_path=config_path)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "--extra redis --extra browser"


def test_explicit_extras_keep_runtime_required_redis_without_duplicates():
    proc = _run(
        "postgres,postgres",
        stream_bridge_redis_url="redis://redis:6379/0",
    )

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "--extra postgres --extra redis"


def test_empty_string_yields_empty_flags():
    proc = _run("")
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""


@pytest.mark.parametrize(
    "bad_value",
    [
        "; rm -rf /",  # the canonical injection attempt
        "$(whoami)",  # command substitution
        "`echo bad`",  # backticks
        "postgres;evil",  # mixed legal+illegal in a single token
        "1postgres",  # leading digit
        "-postgres",  # leading hyphen
        "post gres extra/path",  # contains slash
    ],
)
def test_metacharacters_abort_with_nonzero_exit(bad_value):
    proc = _run(bad_value)
    assert proc.returncode != 0, f"expected abort for {bad_value!r}, got 0"
    assert "is invalid" in proc.stderr
    assert proc.stdout.strip() == ""


def test_underscores_and_hyphens_in_name_are_allowed():
    """Mirrors uv's accepted shape for `[project.optional-dependencies]` keys."""
    proc = _run("post_gres,post-gres")
    assert proc.returncode == 0
    assert proc.stdout.strip() == "--extra post_gres --extra post-gres"


# ── Dependency-sync failure branch ──────────────────────────────────────────
#
# The self-heal retry reuses `--locked`, so a lock that genuinely disagrees with
# the environment fails the same way twice. `set -e` already stops the script
# there -- these tests pin that the handoff to uvicorn is never reached, and
# that the operator is told what to do instead of reading a bare uv traceback.
#
# `/app/backend` only exists inside the container, so the sync block is sliced
# out of the real script and run against a stub `uv`. The block is read from
# the file rather than duplicated here: editing the script changes what runs.

_SYNC_BLOCK_START = "# ── Sync dependencies (with self-heal) ──"
_SYNC_BLOCK_END = "# ── Hand off to uvicorn ──"

_STUB_UV_ALWAYS_FAILS_SYNC = """#!/bin/sh
# `uv venv` succeeds so the retry is actually reached; every sync fails.
case "$1" in
  sync) exit 1 ;;
  *) exit 0 ;;
esac
"""

_STUB_UV_SUCCEEDS = """#!/bin/sh
exit 0
"""

_STUB_UV_FAILS_THEN_SUCCEEDS = """#!/bin/sh
case "$1" in
  sync)
    if [ -f "$STUB_UV_STATE/first_sync_done" ]; then exit 0; fi
    : > "$STUB_UV_STATE/first_sync_done"
    exit 1
    ;;
  *) exit 0 ;;
esac
"""


def _sync_block() -> str:
    content = ENTRYPOINT.read_text(encoding="utf-8")
    start = content.index(_SYNC_BLOCK_START)
    end = content.index(_SYNC_BLOCK_END)
    return content[start:end]


def _run_sync_block(tmp_path: Path, stub_uv: str) -> subprocess.CompletedProcess[str]:
    """Execute the script's real sync block with a stubbed `uv` on PATH."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    uv_stub = bin_dir / "uv"
    uv_stub.write_text(stub_uv, encoding="utf-8")
    uv_stub.chmod(0o755)

    state_dir = tmp_path / "state"
    state_dir.mkdir()

    # `cd` is shadowed because /app/backend does not exist outside the
    # container; everything else in the block runs verbatim.
    script = f'set -e\ncd() {{ :; }}\nEXTRAS_FLAGS=""\n{_sync_block()}\necho "REACHED_HANDOFF"\n'

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["STUB_UV_STATE"] = str(state_dir)
    return subprocess.run(["sh", "-c", script], capture_output=True, text=True, check=False, env=env, cwd=tmp_path)


def test_successful_sync_reaches_the_uvicorn_handoff(tmp_path: Path):
    proc = _run_sync_block(tmp_path, _STUB_UV_SUCCEEDS)

    assert proc.returncode == 0, proc.stderr
    assert "REACHED_HANDOFF" in proc.stdout


def test_self_heal_retry_still_reaches_the_handoff(tmp_path: Path):
    proc = _run_sync_block(tmp_path, _STUB_UV_FAILS_THEN_SUCCEEDS)

    assert proc.returncode == 0, proc.stderr
    assert "recreating .venv" in proc.stdout
    assert "REACHED_HANDOFF" in proc.stdout


def test_failed_retry_aborts_before_starting_uvicorn(tmp_path: Path):
    proc = _run_sync_block(tmp_path, _STUB_UV_ALWAYS_FAILS_SYNC)

    assert proc.returncode != 0, "startup continued past an unsatisfied lock"
    assert "REACHED_HANDOFF" not in proc.stdout, "uvicorn would have been started against a stale or missing environment"


def test_failed_retry_tells_the_operator_how_to_recover(tmp_path: Path):
    proc = _run_sync_block(tmp_path, _STUB_UV_ALWAYS_FAILS_SYNC)

    assert "make install" in proc.stderr, f"no recovery guidance on stderr: {proc.stderr!r}"
