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
    """Non-persistent dev startup should force LangGraph file persistence off."""
    command = (
        f"source '{HELPER_PATH}' && "
        "unset DEER_FLOW_CONFIG_PATH LANGGRAPH_DISABLE_FILE_PERSISTENCE && "
        "prepare_langgraph_dev_runtime '/root/deer-flow' && "
        'printf "%s" "$LANGGRAPH_DISABLE_FILE_PERSISTENCE"'
    )

    output = subprocess.check_output(["bash", "-lc", command], text=True).strip()

    assert output == "true"


def test_prepare_langgraph_dev_runtime_preserves_persistent_checkpointer_state():
    """Persistent sqlite/postgres checkpointers should keep LangGraph metadata."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_root = Path(tmpdir)
        state_dir = repo_root / "backend" / ".langgraph_api"
        state_dir.mkdir(parents=True)
        (state_dir / "sentinel.txt").write_text("keep")
        config_path = repo_root / "config.yaml"
        config_path.write_text("checkpointer:\n  type: sqlite\n  connection_string: checkpoints.db\n", encoding="utf-8")

        command = (
            f"source '{HELPER_PATH}' && "
            "unset LANGGRAPH_DISABLE_FILE_PERSISTENCE && "
            f"prepare_langgraph_dev_runtime '{repo_root}' && "
            f"if [ -e '{state_dir}/sentinel.txt' ]; then printf 'kept:'; else printf 'missing:'; fi && "
            'printf "%s" "${LANGGRAPH_DISABLE_FILE_PERSISTENCE:-unset}"'
        )

        output = subprocess.check_output(["bash", "-lc", command], text=True).strip()

    assert output == "kept:unset"


def test_dev_entrypoints_apply_langgraph_runtime_reset():
    """All development entrypoints should delegate runtime preparation to the helper."""
    serve_text = SERVE_SCRIPT.read_text()
    daemon_text = DAEMON_SCRIPT.read_text()
    docker_text = DOCKER_COMPOSE.read_text()
    backend_make_text = BACKEND_MAKEFILE.read_text()

    assert 'source "$REPO_ROOT/scripts/langgraph-dev-state.sh"' in serve_text
    assert 'prepare_langgraph_dev_runtime "$REPO_ROOT"' in serve_text
    prepare_index = serve_text.index('prepare_langgraph_dev_runtime "$REPO_ROOT"')
    langgraph_flags_index = serve_text.index('LANGGRAPH_EXTRA_FLAGS=""')
    assert prepare_index < langgraph_flags_index

    assert 'source "$REPO_ROOT/scripts/langgraph-dev-state.sh"' in daemon_text
    assert 'prepare_langgraph_dev_runtime "$REPO_ROOT"' in daemon_text

    assert ". /app/scripts/langgraph-dev-state.sh" in docker_text
    assert "prepare_langgraph_dev_runtime /app" in docker_text
    assert "../scripts/:/app/scripts/" in docker_text

    assert "langgraph-dev-state.sh" in backend_make_text
    assert "prepare_langgraph_dev_runtime" in backend_make_text
