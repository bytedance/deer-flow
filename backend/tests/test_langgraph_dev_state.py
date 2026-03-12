"""Regression tests for LangGraph dev runtime state handling."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
HELPER_PATH = REPO_ROOT / "scripts" / "langgraph-dev-state.sh"
SERVE_SCRIPT = REPO_ROOT / "scripts" / "serve.sh"
DAEMON_SCRIPT = REPO_ROOT / "scripts" / "start-daemon.sh"
DOCKER_COMPOSE = REPO_ROOT / "docker" / "docker-compose-dev.yaml"
BACKEND_MAKEFILE = REPO_ROOT / "backend" / "Makefile"


def test_reset_langgraph_dev_state_removes_runtime_dir():
    """Dev startup should discard stale LangGraph runtime state."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_root = Path(tmpdir)
        state_dir = repo_root / "backend" / ".langgraph_api"
        state_dir.mkdir(parents=True)
        (state_dir / "sentinel.txt").write_text("stale")

        command = (
            f"source '{HELPER_PATH}' && "
            f"reset_langgraph_dev_state '{repo_root}' && "
            f"if [ -e '{state_dir}' ]; then echo exists; else echo missing; fi"
        )

        output = subprocess.check_output(["bash", "-lc", command], text=True).strip()

    assert output == "missing"


def test_prepare_langgraph_dev_env_disables_file_persistence():
    """Dev startup should force LangGraph's file persistence off."""
    command = (
        f"source '{HELPER_PATH}' && "
        "unset LANGGRAPH_DISABLE_FILE_PERSISTENCE && "
        "prepare_langgraph_dev_env && "
        'printf "%s" "$LANGGRAPH_DISABLE_FILE_PERSISTENCE"'
    )

    output = subprocess.check_output(["bash", "-lc", command], text=True).strip()

    assert output == "true"


def test_dev_entrypoints_apply_langgraph_runtime_reset():
    """All development entrypoints should start LangGraph from a clean runtime."""
    serve_text = SERVE_SCRIPT.read_text()
    daemon_text = DAEMON_SCRIPT.read_text()
    docker_text = DOCKER_COMPOSE.read_text()
    backend_make_text = BACKEND_MAKEFILE.read_text()

    assert 'source "$REPO_ROOT/scripts/langgraph-dev-state.sh"' in serve_text
    assert 'reset_langgraph_dev_state "$REPO_ROOT"' in serve_text
    assert "prepare_langgraph_dev_env" in serve_text
    reset_index = serve_text.index('reset_langgraph_dev_state "$REPO_ROOT"')
    langgraph_flags_index = serve_text.index('LANGGRAPH_EXTRA_FLAGS=""')
    assert reset_index < langgraph_flags_index

    assert 'source "$REPO_ROOT/scripts/langgraph-dev-state.sh"' in daemon_text
    assert 'reset_langgraph_dev_state "$REPO_ROOT"' in daemon_text
    assert "prepare_langgraph_dev_env" in daemon_text

    assert "rm -rf /app/backend/.langgraph_api" in docker_text
    assert "LANGGRAPH_DISABLE_FILE_PERSISTENCE=true" in docker_text

    assert "langgraph-dev-state.sh" in backend_make_text
    assert "reset_langgraph_dev_state" in backend_make_text
    assert "prepare_langgraph_dev_env" in backend_make_text
