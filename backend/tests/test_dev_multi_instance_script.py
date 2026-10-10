"""Tests for the two-Gateway local harness (``scripts/dev_multi_instance.{sh,py}``).

The shell entry point owns containers and processes; the Python helper owns the
parts that decide whether the pair can start at all. The key contract pinned
here: the generated ``config.yaml`` passes the *real* multi-instance startup
gate (``app.gateway.deps._enforce_postgres_for_multi_worker``) for any base
config, while leaving the developer's other sections untouched.
"""

from __future__ import annotations

import base64
import importlib.util
import logging
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from app.gateway.deps import _enforce_postgres_for_multi_worker, _validate_memory_retrieval_index
from deerflow.config.app_config import AppConfig
from deerflow.config.deployment_config import MULTI_INSTANCE_ENV_VAR, multi_instance_declaration

REPO_ROOT = Path(__file__).resolve().parents[2]
HELPER_PATH = REPO_ROOT / "scripts" / "dev_multi_instance.py"
SHELL_PATH = REPO_ROOT / "scripts" / "dev_multi_instance.sh"

_spec = importlib.util.spec_from_file_location("deerflow_dev_multi_instance", HELPER_PATH)
assert _spec is not None and _spec.loader is not None
mi = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = mi  # dataclasses resolve string annotations through sys.modules
_spec.loader.exec_module(mi)

DATABASE_URL = "postgresql://deerflow:secret@127.0.0.1:55432/deerflow"
REDIS_URL = "redis://127.0.0.1:56379/0"


@pytest.fixture(autouse=True)
def _isolated_gate_env(monkeypatch):
    """The gate also reads worker-count and declaration variables from the shell."""
    for name in ("GATEWAY_WORKERS", "WEB_CONCURRENCY", MULTI_INSTANCE_ENV_VAR, "DEER_FLOW_STREAM_BRIDGE_REDIS_URL", mi.RETRIEVAL_INDEX_ENV_VAR):
        monkeypatch.delenv(name, raising=False)


def _overlay(base: dict, **kwargs):
    return mi.build_multi_instance_config(base, database_url=DATABASE_URL, redis_url=REDIS_URL, **kwargs)


# ---------------------------------------------------------------------------
# Overlay semantics
# ---------------------------------------------------------------------------


def test_overlay_sets_every_multi_instance_prerequisite():
    config, _notes = _overlay({})

    assert config["deployment"]["multi_instance"] is True
    assert config["database"]["backend"] == "postgres"
    assert config["database"]["postgres_url"] == DATABASE_URL
    assert config["run_events"]["backend"] == "db"
    assert config["run_ownership"]["heartbeat_enabled"] is True
    assert config["stream_bridge"] == {"type": "redis", "redis_url": REDIS_URL}
    # One shared file, a per-process index directory chosen by the environment.
    assert config["memory"]["backend_config"]["retrieval_index_path"] == f"${mi.RETRIEVAL_INDEX_ENV_VAR}"


def test_overlay_preserves_unrelated_base_sections_without_mutating_the_base():
    base = {
        "config_version": 57,
        "models": [{"name": "m1", "use": "langchain_openai:ChatOpenAI", "model": "gpt-x"}],
        "tools": [{"name": "web_search", "use": "deerflow.community.ddg_search.tools:web_search_tool"}],
        "database": {"backend": "sqlite", "sqlite_dir": ".deer-flow/data", "pool_recycle": 120},
        "run_ownership": {"lease_seconds": 15, "grace_seconds": 5, "heartbeat_enabled": False},
        "run_events": {"backend": "memory", "max_trace_content": 2048},
        "memory": {"enabled": True, "backend_config": {"debounce_seconds": 5, "storage_path": ""}},
        "scheduler": {"enabled": False, "multi_instance": False},
    }
    snapshot = yaml.safe_dump(base)

    config, _notes = _overlay(base)

    assert yaml.safe_dump(base) == snapshot, "the base mapping must not be mutated"
    assert config["config_version"] == 57
    assert config["models"] == base["models"]
    assert config["tools"] == base["tools"]
    assert config["database"]["pool_recycle"] == 120
    assert config["run_ownership"]["lease_seconds"] == 15
    assert config["run_ownership"]["grace_seconds"] == 5
    assert config["run_events"]["max_trace_content"] == 2048
    assert config["memory"]["backend_config"]["debounce_seconds"] == 5
    # A disabled scheduler is left alone.
    assert config["scheduler"] == {"enabled": False, "multi_instance": False}


def test_overlay_neutralizes_settings_the_gate_refuses():
    base = {
        "tools": [
            {"name": "web_search", "use": "deerflow.community.ddg_search.tools:web_search_tool"},
            {"name": "browser_navigate", "use": "deerflow.community.browser_automation.tools:browser_navigate_tool"},
            {"name": "browser_click", "use": "deerflow.community.browser_automation.tools:browser_click_tool"},
        ],
        "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider", "ownership": {"type": "memory"}},
        "scheduler": {"enabled": True},
        "checkpointer": {"type": "sqlite", "connection_string": "checkpoints.db"},
        "channels": {
            "langgraph_url": "http://localhost:8001/api",
            "session": {"assistant_id": "lead_agent"},
            "telegram": {"enabled": True, "bot_token": "$TELEGRAM_BOT_TOKEN"},
            "slack": {"enabled": False},
        },
    }

    config, notes = _overlay(base)

    assert [tool["name"] for tool in config["tools"]] == ["web_search"]
    assert "ownership" not in config["sandbox"]
    assert config["sandbox"]["use"] == "deerflow.sandbox.local:LocalSandboxProvider"
    assert config["scheduler"] == {"enabled": True, "multi_instance": True}
    assert "checkpointer" not in config
    assert config["channels"]["telegram"]["enabled"] is False
    assert config["channels"]["telegram"]["bot_token"] == "$TELEGRAM_BOT_TOKEN"
    assert config["channels"]["slack"]["enabled"] is False
    assert config["channels"]["langgraph_url"] == "http://localhost:8001/api"
    joined = "\n".join(notes)
    for fragment in ("browser_navigate", "sandbox.ownership", "scheduler.multi_instance", "checkpointer", "telegram"):
        assert fragment in joined


def test_overlay_keeps_channels_and_a_postgres_checkpointer_when_asked():
    base = {
        "channels": {"telegram": {"enabled": True}},
        "checkpointer": {"type": "postgres", "connection_string": DATABASE_URL},
    }

    config, _notes = _overlay(base, keep_channels=True)

    assert config["channels"]["telegram"]["enabled"] is True
    assert config["checkpointer"]["type"] == "postgres"


def test_overlay_leaves_non_deermem_memory_backends_alone():
    config, _notes = _overlay({"memory": {"manager_class": "mem0", "backend_config": {"base_url": "https://mem0.example"}}})

    assert config["memory"]["backend_config"] == {"base_url": "https://mem0.example"}


# ---------------------------------------------------------------------------
# The generated file against the real loader and startup gate
# ---------------------------------------------------------------------------


def _load_generated(tmp_path: Path, monkeypatch, base_path: Path, *, index_dir: Path) -> AppConfig:
    out = tmp_path / "state" / "config.yaml"
    extensions = tmp_path / "extensions_config.json"
    extensions.write_text('{"mcpServers": {}, "skills": {}}', encoding="utf-8")
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions))
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path / "home"))
    monkeypatch.setenv(mi.RETRIEVAL_INDEX_ENV_VAR, str(index_dir))
    mi.render_config(base_path, out, database_url=DATABASE_URL, redis_url=REDIS_URL)
    return AppConfig.from_file(str(out))


def test_generated_config_from_the_example_passes_the_real_startup_gate(tmp_path, monkeypatch, caplog):
    config = _load_generated(tmp_path, monkeypatch, REPO_ROOT / "config.example.yaml", index_dir=tmp_path / "index-a")

    assert multi_instance_declaration(config) is not None
    _enforce_postgres_for_multi_worker(config)  # must not raise SystemExit

    with caplog.at_level(logging.WARNING, logger="app.gateway.deps"):
        _validate_memory_retrieval_index(config)
    assert "retrieval index" not in caplog.text, "each process must keep its index outside the shared storage_path"
    assert config.memory.backend_config["retrieval_index_path"] == str(tmp_path / "index-a")


def test_generated_config_from_a_hostile_base_passes_the_real_startup_gate(tmp_path, monkeypatch):
    base_path = tmp_path / "base.yaml"
    base_path.write_text(
        yaml.safe_dump(
            {
                "config_version": 1,
                "models": [],
                "tools": [{"name": "browser_navigate", "use": "deerflow.community.browser_automation.tools:browser_navigate_tool", "group": "web"}],
                "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider", "ownership": {"type": "memory"}},
                "scheduler": {"enabled": True},
                "database": {"backend": "sqlite", "sqlite_dir": ".deer-flow/data"},
                "run_events": {"backend": "jsonl"},
                "stream_bridge": {"type": "memory"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv(MULTI_INSTANCE_ENV_VAR, "1")
    with pytest.raises(SystemExit):
        # Sanity: the base itself is refused under a multi-instance declaration.
        _enforce_postgres_for_multi_worker(AppConfig.from_file(str(base_path)))
    monkeypatch.delenv(MULTI_INSTANCE_ENV_VAR)

    config = _load_generated(tmp_path, monkeypatch, base_path, index_dir=tmp_path / "index-b")

    _enforce_postgres_for_multi_worker(config)


def test_each_process_resolves_its_own_retrieval_index(tmp_path, monkeypatch):
    out = tmp_path / "config.yaml"
    mi.render_config(REPO_ROOT / "config.example.yaml", out, database_url=DATABASE_URL, redis_url=REDIS_URL)
    raw = yaml.safe_load(out.read_text(encoding="utf-8"))
    resolved = []
    for name in ("a", "b"):
        monkeypatch.setenv(mi.RETRIEVAL_INDEX_ENV_VAR, str(tmp_path / "index" / name))
        resolved.append(AppConfig.resolve_env_variables(raw)["memory"]["backend_config"]["retrieval_index_path"])

    assert resolved[0] != resolved[1]


def test_render_config_writes_a_private_file_with_a_generated_header(tmp_path):
    out = tmp_path / "nested" / "config.yaml"

    notes = mi.render_config(REPO_ROOT / "config.example.yaml", out, database_url=DATABASE_URL, redis_url=REDIS_URL)

    assert isinstance(notes, list)
    text = out.read_text(encoding="utf-8")
    assert text.startswith("# Generated by scripts/dev_multi_instance.sh")
    assert stat.S_IMODE(out.stat().st_mode) == 0o600, "the base config may carry model API keys"
    assert yaml.safe_load(text)["deployment"]["multi_instance"] is True


# ---------------------------------------------------------------------------
# Shared secrets and nginx front
# ---------------------------------------------------------------------------


def test_secrets_file_is_private_complete_and_stable(tmp_path):
    path = tmp_path / "secrets.env"

    first = mi.ensure_secrets_file(path)
    second = mi.ensure_secrets_file(path)

    assert first == second, "an existing secrets file is reused, never regenerated"
    assert set(first) == set(mi.SHARED_SECRET_NAMES)
    assert all(value for value in first.values())
    assert len(base64.urlsafe_b64decode(first["DEER_FLOW_CREDENTIALS_KEY"])) == 32, "must be a raw Fernet key"
    assert first["AUTH_JWT_SECRET"] != first["DEER_FLOW_INTERNAL_AUTH_TOKEN"]
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    # Shell-sourceable KEY=value lines.
    assert sorted(line.split("=", 1)[0] for line in path.read_text(encoding="utf-8").splitlines() if line and not line.startswith("#")) == sorted(mi.SHARED_SECRET_NAMES)


def test_nginx_conf_balances_both_gateways(tmp_path):
    text = mi.render_nginx_conf(listen_port=2027, gateway_ports=[8001, 8011], frontend_port=3000, state_dir=tmp_path)

    assert "listen 127.0.0.1:2027;" in text
    assert "server 127.0.0.1:8001;" in text
    assert "server 127.0.0.1:8011;" in text
    assert "X-DeerFlow-Upstream $upstream_addr" in text
    assert str(tmp_path / "run" / "nginx.pid") in text


@pytest.mark.skipif(shutil.which("nginx") is None, reason="nginx is not installed")
def test_nginx_conf_is_accepted_by_nginx(tmp_path):
    for sub in ("run", "logs", "nginx/temp"):  # the shell creates these before nginx starts
        (tmp_path / sub).mkdir(parents=True)
    conf = tmp_path / "nginx" / "nginx.conf"
    conf.write_text(mi.render_nginx_conf(listen_port=2027, gateway_ports=[8001, 8011], frontend_port=3000, state_dir=tmp_path), encoding="utf-8")

    result = subprocess.run(["nginx", "-t", "-p", str(tmp_path / "nginx"), "-c", str(conf)], capture_output=True, text=True, timeout=30)

    assert result.returncode == 0, result.stderr


# ---------------------------------------------------------------------------
# Check helpers
# ---------------------------------------------------------------------------


def test_parse_sse_events_keeps_ids_and_event_names():
    lines = [
        ": comment",
        "id: 1-0",
        "event: metadata",
        'data: {"run_id": "r"}',
        "",
        "event: heartbeat",
        "data: {}",
        "",
        "id: 2-0",
        "event: end",
        "data: null",
        "",
    ]

    events = list(mi.parse_sse_events(lines))

    assert [(event.id, event.event) for event in events] == [("1-0", "metadata"), (None, "heartbeat"), ("2-0", "end")]
    assert events[0].data == '{"run_id": "r"}'


def test_check_exit_code_reflects_failures_only():
    assert mi.exit_code([mi.CheckResult("a", mi.PASS, ""), mi.CheckResult("b", mi.SKIP, "")]) == 0
    assert mi.exit_code([mi.CheckResult("a", mi.PASS, ""), mi.CheckResult("b", mi.FAIL, "")]) == 1


# ---------------------------------------------------------------------------
# Shell entry point smoke tests (no Docker, no processes)
# ---------------------------------------------------------------------------


def test_shell_script_parses():
    result = subprocess.run(["bash", "-n", str(SHELL_PATH)], capture_output=True, text=True, timeout=30)

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("flag", ["--help", "help", "-h"])
def test_shell_script_help_lists_every_command_without_side_effects(tmp_path, flag):
    env = {**os.environ, "DEERFLOW_MI_STATE_DIR": str(tmp_path / "state"), "PATH": os.environ.get("PATH", "")}

    result = subprocess.run(["bash", str(SHELL_PATH), flag], capture_output=True, text=True, timeout=30, env=env)

    assert result.returncode == 0, result.stderr
    for command in ("up", "down", "status", "logs", "check", "restart"):
        assert f"  {command}" in result.stdout
    assert not (tmp_path / "state").exists(), "help must not create harness state"


def test_shell_script_rejects_unknown_commands(tmp_path):
    env = {**os.environ, "DEERFLOW_MI_STATE_DIR": str(tmp_path / "state")}

    result = subprocess.run(["bash", str(SHELL_PATH), "frobnicate"], capture_output=True, text=True, timeout=30, env=env)

    assert result.returncode != 0
    assert "Unknown command" in result.stderr


def test_makefile_exposes_harness_targets():
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")

    for target in ("dev-multi", "dev-multi-check", "dev-multi-down"):
        assert f"\n{target}:" in makefile
        assert f"make {target} " in makefile, f"`make help` should list {target}"
