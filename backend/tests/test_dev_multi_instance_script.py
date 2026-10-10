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
from support.shell import require_script_bash

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


SANDBOX_PREFIX = "deer-flow-mi-0123456789-sandbox"


def _overlay(base: dict, **kwargs):
    return mi.build_multi_instance_config(base, database_url=DATABASE_URL, redis_url=REDIS_URL, sandbox_container_prefix=SANDBOX_PREFIX, **kwargs)


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
    assert config["sandbox"]["ownership"] == {"type": "redis", "redis_url": REDIS_URL}
    assert config["sandbox"]["use"] == "deerflow.sandbox.local:LocalSandboxProvider"
    assert "container_prefix" not in config["sandbox"], "only the local AIO provider names containers"
    assert config["scheduler"] == {"enabled": True, "multi_instance": True}
    assert "checkpointer" not in config
    assert config["channels"]["telegram"]["enabled"] is False
    assert config["channels"]["telegram"]["bot_token"] == "$TELEGRAM_BOT_TOKEN"
    assert config["channels"]["slack"]["enabled"] is False
    assert config["channels"]["langgraph_url"] == "http://localhost:8001/api"
    joined = "\n".join(notes)
    for fragment in ("browser_navigate", "sandbox.ownership", "scheduler.multi_instance", "checkpointer", "telegram"):
        assert fragment in joined


def test_overlay_keeps_channels_when_asked():
    config, _notes = _overlay({"channels": {"telegram": {"enabled": True}}}, keep_channels=True)

    assert config["channels"]["telegram"]["enabled"] is True


def test_overlay_drops_a_postgres_checkpointer_pointing_at_the_developers_database():
    # An explicit checkpointer section wins over database.postgres_url for LangGraph
    # checkpoints and the Store, so keeping it would write into the real database.
    base = {"checkpointer": {"type": "postgres", "connection_string": "postgresql://me@db.internal:5432/prod"}}

    config, notes = _overlay(base)

    assert "checkpointer" not in config
    assert any("checkpointer" in note for note in notes)


def test_overlay_points_explicit_sandbox_ownership_at_the_harness_redis():
    base = {
        "sandbox": {
            "use": "deerflow.sandbox.local:LocalSandboxProvider",
            "ownership": {"type": "redis", "redis_url": "redis://prod-redis:6379/3", "renewal_interval_seconds": 7.5, "ttl_multiplier": 3},
        }
    }

    config, notes = _overlay(base)

    assert config["sandbox"]["ownership"] == {"type": "redis", "redis_url": REDIS_URL, "renewal_interval_seconds": 7.5, "ttl_multiplier": 3}
    assert any("sandbox.ownership" in note for note in notes)


def test_overlay_gives_local_aio_sandboxes_a_harness_container_prefix():
    base = {"sandbox": {"use": "deerflow.community.aio_sandbox:AioSandboxProvider", "container_prefix": "deer-flow-sandbox"}}

    config, notes = _overlay(base)

    assert config["sandbox"]["container_prefix"] == SANDBOX_PREFIX
    assert any("container_prefix" in note for note in notes)
    # Omitted prefix (the provider default) is replaced too.
    config, _notes = _overlay({"sandbox": {"use": "deerflow.community.aio_sandbox:AioSandboxProvider"}})
    assert config["sandbox"]["container_prefix"] == SANDBOX_PREFIX


def test_overlay_leaves_provisioner_backed_aio_prefixes_alone():
    base = {"sandbox": {"use": "deerflow.community.aio_sandbox:AioSandboxProvider", "provisioner_url": "http://provisioner:8002"}}

    config, _notes = _overlay(base)

    assert "container_prefix" not in config["sandbox"]


def test_sandbox_container_prefix_is_stable_per_state_dir(tmp_path):
    first = mi.sandbox_container_prefix(tmp_path / "a")

    assert first == mi.sandbox_container_prefix(tmp_path / "a")
    assert first != mi.sandbox_container_prefix(tmp_path / "b")
    assert first.startswith("deer-flow-mi-") and first.endswith("-sandbox")
    assert all(ch.isalnum() or ch in "-_." for ch in first)


@pytest.mark.parametrize(
    "memory",
    [
        {"backend_config": {"storage_path": "/srv/real-memory"}},
        {"storage_path": "/srv/real-memory"},  # legacy pre-abstraction spelling, auto-migrated on load
    ],
)
def test_overlay_keeps_deermem_data_inside_the_harness_home(memory):
    config, notes = _overlay({"memory": memory})

    assert "storage_path" not in config["memory"]
    assert "storage_path" not in config["memory"]["backend_config"]
    assert any("storage_path" in note for note in notes)


def test_overlay_keeps_other_data_roots_inside_the_harness():
    base = {
        "blob_storage": {"enabled": True, "backend": "local_fs", "backend_config": {"root": "/mnt/shared/deerflow-blobs"}},
        "database": {"checkpoint_cache": {"type": "redis", "redis_url": "redis://prod-redis:6379/1", "max_entries": 64}},
    }

    config, notes = _overlay(base)

    assert "root" not in config["blob_storage"]["backend_config"]
    assert config["database"]["checkpoint_cache"] == {"type": "redis", "redis_url": REDIS_URL, "max_entries": 64}
    joined = "\n".join(notes)
    assert "blob_storage" in joined and "checkpoint_cache" in joined


def test_overlay_leaves_non_deermem_memory_backends_alone_but_says_so():
    config, notes = _overlay({"memory": {"manager_class": "mem0", "backend_config": {"base_url": "https://mem0.example"}}})

    assert config["memory"]["backend_config"] == {"base_url": "https://mem0.example"}
    assert any("mem0" in note for note in notes)


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
    mi.render_config(base_path, out, database_url=DATABASE_URL, redis_url=REDIS_URL, state_dir=tmp_path / "state")
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
    mi.render_config(REPO_ROOT / "config.example.yaml", out, database_url=DATABASE_URL, redis_url=REDIS_URL, state_dir=tmp_path)
    raw = yaml.safe_load(out.read_text(encoding="utf-8"))
    resolved = []
    for name in ("a", "b"):
        monkeypatch.setenv(mi.RETRIEVAL_INDEX_ENV_VAR, str(tmp_path / "index" / name))
        resolved.append(AppConfig.resolve_env_variables(raw)["memory"]["backend_config"]["retrieval_index_path"])

    assert resolved[0] != resolved[1]


@pytest.mark.skipif(os.name == "nt", reason="chmod cannot express owner-only modes on Windows")
def test_render_config_writes_a_private_file_with_a_generated_header(tmp_path):
    out = tmp_path / "nested" / "config.yaml"

    notes = mi.render_config(REPO_ROOT / "config.example.yaml", out, database_url=DATABASE_URL, redis_url=REDIS_URL, state_dir=tmp_path)

    assert isinstance(notes, list)
    text = out.read_text(encoding="utf-8")
    assert text.startswith("# Generated by scripts/dev_multi_instance.sh")
    assert stat.S_IMODE(out.stat().st_mode) == 0o600, "the base config may carry model API keys"
    assert yaml.safe_load(text)["deployment"]["multi_instance"] is True


# ---------------------------------------------------------------------------
# Shared secrets and nginx front
# ---------------------------------------------------------------------------


@pytest.mark.skipif(os.name == "nt", reason="chmod cannot express owner-only modes on Windows")
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


def _nginx_quoted(path: Path) -> str:
    """Return the quoted nginx string literal ``render_nginx_conf`` must emit for *path*.

    nginx treats a backslash as an escape character inside quoted strings, so a
    Windows separator has to be doubled in the generated config; building the
    expectation here keeps the assertion correct on every platform.
    """
    return '"' + str(path).replace("\\", "\\\\").replace('"', '\\"') + '"'


def test_nginx_conf_balances_both_gateways(tmp_path):
    text = mi.render_nginx_conf(listen_port=2027, gateway_ports=[8001, 8011], frontend_port=3000, state_dir=tmp_path)

    assert "listen 127.0.0.1:2027;" in text
    assert "server 127.0.0.1:8001;" in text
    assert "server 127.0.0.1:8011;" in text
    assert "X-DeerFlow-Upstream $upstream_addr" in text
    assert _nginx_quoted(tmp_path / "run" / "nginx.pid") in text


def test_nginx_conf_quotes_paths_with_whitespace(tmp_path):
    state = tmp_path / "mi state"

    text = mi.render_nginx_conf(listen_port=2027, gateway_ports=[8001, 8011], frontend_port=3000, state_dir=state)

    assert f"pid {_nginx_quoted(state / 'run' / 'nginx.pid')};" in text
    assert f"access_log {_nginx_quoted(state / 'logs' / 'nginx-access.log')};" in text
    assert f"proxy_temp_path {_nginx_quoted(state / 'nginx' / 'temp' / 'proxy')};" in text


def test_nginx_conf_rejects_paths_nginx_would_interpolate(tmp_path):
    with pytest.raises(ValueError):
        mi.render_nginx_conf(listen_port=2027, gateway_ports=[8001], frontend_port=3000, state_dir=tmp_path / "$HOME")


@pytest.mark.skipif(shutil.which("nginx") is None, reason="nginx is not installed")
@pytest.mark.parametrize("state_name", ["state", "mi state"])
def test_nginx_conf_is_accepted_by_nginx(tmp_path, state_name):
    state = tmp_path / state_name
    for sub in ("run", "logs", "nginx/temp"):  # the shell creates these before nginx starts
        (state / sub).mkdir(parents=True)
    conf = state / "nginx" / "nginx.conf"
    conf.write_text(mi.render_nginx_conf(listen_port=2027, gateway_ports=[8001, 8011], frontend_port=3000, state_dir=state), encoding="utf-8")

    result = subprocess.run(["nginx", "-t", "-p", str(state / "nginx"), "-c", str(conf)], capture_output=True, text=True, timeout=30)

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


def _offline_harness(tmp_path, handler, **kwargs):
    import httpx

    h = mi.Harness(gateways=[("A", "http://a.test"), ("B", "http://b.test")], nginx_url=None, state_dir=tmp_path, with_llm=False, timeout=5.0, **kwargs)
    h.http = httpx.Client(transport=httpx.MockTransport(handler))
    return h


def test_sse_resume_never_starts_a_run_when_model_discovery_failed(tmp_path):
    def refuse(request):
        raise AssertionError(f"unexpected request {request.method} {request.url}")

    h = _offline_harness(tmp_path, refuse)
    h.thread_id = "t-1"
    h.models = None  # the internal-token check failed or was skipped

    with pytest.raises(mi.CheckSkipped, match="--with-llm"):
        mi._check_sse_resume(h)


def test_sse_read_enforces_its_budget_while_only_heartbeats_arrive(tmp_path):
    import time as _time

    def heartbeats():
        # A live idle run: comment heartbeats only, for far longer than the budget.
        for _ in range(300):
            _time.sleep(0.01)
            yield b": heartbeat\n\n"

    import httpx

    h = _offline_harness(tmp_path, lambda request: httpx.Response(200, headers={"content-type": "text/event-stream"}, content=heartbeats()))
    started = _time.monotonic()

    with pytest.raises(mi.CheckFailed, match="budget"):
        mi._read_stream(h, "http://a.test", "/api/threads/t/runs/r/join", budget=0.3)

    assert _time.monotonic() - started < 2.0


# ---------------------------------------------------------------------------
# Shell entry point smoke tests (no Docker, no processes)
# ---------------------------------------------------------------------------


def test_shell_script_parses():
    result = subprocess.run([require_script_bash(), "-n", str(SHELL_PATH)], capture_output=True, text=True, timeout=30)

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("flag", ["--help", "help", "-h"])
def test_shell_script_help_lists_every_command_without_side_effects(tmp_path, flag):
    env = {**os.environ, "DEERFLOW_MI_STATE_DIR": str(tmp_path / "state"), "PATH": os.environ.get("PATH", "")}

    result = subprocess.run([require_script_bash(), str(SHELL_PATH), flag], capture_output=True, text=True, timeout=30, env=env)

    assert result.returncode == 0, result.stderr
    for command in ("up", "down", "status", "logs", "check", "restart"):
        assert f"  {command}" in result.stdout
    assert not (tmp_path / "state").exists(), "help must not create harness state"


def test_shell_script_rejects_unknown_commands(tmp_path):
    env = {**os.environ, "DEERFLOW_MI_STATE_DIR": str(tmp_path / "state")}

    result = subprocess.run([require_script_bash(), str(SHELL_PATH), "frobnicate"], capture_output=True, text=True, timeout=30, env=env)

    assert result.returncode != 0
    assert "Unknown command" in result.stderr


def test_makefile_exposes_harness_targets():
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")

    for target in ("dev-multi", "dev-multi-check", "dev-multi-down"):
        assert f"\n{target}:" in makefile
        assert f"make {target} " in makefile, f"`make help` should list {target}"


# ---------------------------------------------------------------------------
# Shell lifecycle against stubbed docker / uv / lsof and a fake Gateway
# ---------------------------------------------------------------------------

_DOCKER_STUB = r"""#!/usr/bin/env bash
dir="$(cd "$(dirname "$0")" && pwd)"
state="$dir/containers"
mkdir -p "$state"
{ printf 'docker'; printf ' %s' "$@"; printf '\n'; } >>"$dir/docker.log"
cmd="$1"
shift
case "$cmd" in
    info) exit 0 ;;
    inspect)
        fmt=""
        if [ "$1" = "-f" ]; then fmt="$2"; shift 2; fi
        [ -d "$state/$1" ] || exit 1
        case "$fmt" in
            *state-dir*) cat "$state/$1/deerflow.harness.state-dir" 2>/dev/null; echo ;;
            *deerflow.harness*) cat "$state/$1/deerflow.harness" 2>/dev/null; echo ;;
            *) echo running ;;
        esac
        ;;
    run)
        name=""
        labels=""
        while [ $# -gt 0 ]; do
            case "$1" in
                --name) name="$2"; shift 2 ;;
                --label) labels="$labels$2
"; shift 2 ;;
                -e | -p) shift 2 ;;
                *) shift ;;
            esac
        done
        mkdir -p "$state/$name"
        printf '%s' "$labels" | while IFS= read -r kv; do
            [ -n "$kv" ] && printf '%s' "${kv#*=}" >"$state/$name/${kv%%=*}"
        done
        echo "id-$name"
        ;;
    exec)
        case "$*" in *redis-cli*) echo PONG ;; esac
        ;;
    rm)
        for arg in "$@"; do
            case "$arg" in -*) ;; *) rm -rf "$state/$arg" ;; esac
        done
        ;;
esac
exit 0
"""

_UV_STUB = r"""#!/usr/bin/env bash
dir="$(cd "$(dirname "$0")" && pwd)"
case "$*" in
    *"print(sys.executable)"*) echo "$dir/python" ;;
esac
exit 0
"""

_PYTHON_STUB = r"""#!/usr/bin/env bash
dir="$(cd "$(dirname "$0")" && pwd)"
if [ "${1:-}" = "-m" ] && [ "${2:-}" = "uvicorn" ]; then
    port=""
    previous=""
    for arg in "$@"; do
        [ "$previous" = "--port" ] && port="$arg"
        previous="$arg"
    done
    exec "$REAL_PYTHON" "$dir/fake_gateway.py" app.gateway.app:app "$port"
fi
exec "$REAL_PYTHON" "$@"
"""

_FAKE_GATEWAY = """import sys
from http.server import BaseHTTPRequestHandler, HTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *args):
        pass


HTTPServer(("127.0.0.1", int(sys.argv[2])), Handler).serve_forever()
"""

# Ports listed in busy-from-<port> report busy from that call number on; every
# other query falls through to the real lsof (or "free" when it is missing).
_LSOF_STUB = r"""#!/usr/bin/env bash
dir="$(cd "$(dirname "$0")" && pwd)"
port=""
for arg in "$@"; do
    case "$arg" in -iTCP:*) port="${arg#-iTCP:}" ;; esac
done
count=$(( $(cat "$dir/lsof-count-$port" 2>/dev/null || echo 0) + 1 ))
echo "$count" >"$dir/lsof-count-$port"
if [ -f "$dir/busy-from-$port" ] && [ "$count" -ge "$(cat "$dir/busy-from-$port")" ]; then
    echo 99999
    exit 0
fi
[ -n "$REAL_LSOF" ] || exit 1
exec "$REAL_LSOF" "$@"
"""


def _free_port() -> int:
    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def stubbed_harness(tmp_path):
    if os.name == "nt" or shutil.which("bash") is None or shutil.which("curl") is None:
        pytest.skip("POSIX shell lifecycle test")
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    for name, body in (("docker", _DOCKER_STUB), ("uv", _UV_STUB), ("python", _PYTHON_STUB), ("lsof", _LSOF_STUB), ("fake_gateway.py", _FAKE_GATEWAY)):
        path = stubs / name
        path.write_text(body, encoding="utf-8")
        path.chmod(0o755)
    state = tmp_path / "mi state"  # whitespace on purpose
    ports = {"a": _free_port(), "b": _free_port(), "pg": _free_port(), "redis": _free_port()}
    env = {key: value for key, value in os.environ.items() if not key.startswith(("DEERFLOW_MI_", "DEER_FLOW_"))}
    env.update(
        PATH=f"{stubs}{os.pathsep}{os.environ.get('PATH', '')}",
        REAL_PYTHON=sys.executable,
        REAL_LSOF=shutil.which("lsof") or "",
        DEERFLOW_MI_STATE_DIR=str(state),
        DEERFLOW_MI_BASE_CONFIG=str(REPO_ROOT / "config.example.yaml"),
        DEERFLOW_MI_GATEWAY_A_PORT=str(ports["a"]),
        DEERFLOW_MI_GATEWAY_B_PORT=str(ports["b"]),
        DEERFLOW_MI_POSTGRES_PORT=str(ports["pg"]),
        DEERFLOW_MI_REDIS_PORT=str(ports["redis"]),
        DEERFLOW_MI_HEALTH_TIMEOUT="20",
    )

    def run(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["bash", str(SHELL_PATH), *args], capture_output=True, text=True, timeout=120, env=env)

    yield stubs, state, ports, run

    # Never leak a fake Gateway, whatever the script did.
    for pid_file in (state / "run").glob("*.pid") if (state / "run").is_dir() else []:
        try:
            os.kill(int(pid_file.read_text().strip()), 9)
        except (ValueError, ProcessLookupError):
            pass


def _port_open(port: int) -> bool:
    import socket

    with socket.socket() as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _container(stubs: Path, name: str, *, state_dir: str) -> Path:
    path = stubs / "containers" / name
    path.mkdir(parents=True)
    (path / "deerflow.harness").write_text("dev-multi-instance", encoding="utf-8")
    (path / "deerflow.harness.state-dir").write_text(state_dir, encoding="utf-8")
    return path


def test_up_tears_everything_down_when_b_loses_its_port_after_preflight(stubbed_harness):
    stubs, state, ports, run = stubbed_harness
    (stubs / f"busy-from-{ports['b']}").write_text("2", encoding="utf-8")  # free at preflight, taken when B starts

    result = run("up", "--skip-install", "--no-nginx")

    assert result.returncode != 0
    assert f"Port {ports['b']} is in use" in result.stderr
    assert "Gateway A ready" in result.stdout, "A must have started before B failed"
    assert not _port_open(ports["a"]), "Gateway A must be stopped when up fails"
    assert "Terminated" not in result.stderr, "the Gateway is not a job of the script shell; killing it must not print job notices"
    assert not list((stubs / "containers").iterdir()), "both containers must be removed"
    removals = [line for line in (stubs / "docker.log").read_text().splitlines() if line.startswith("docker rm")]
    assert removals and all(line.startswith("docker rm -f -v ") for line in removals), removals


def test_up_refuses_containers_owned_by_another_state_dir(stubbed_harness):
    stubs, state, _ports, run = stubbed_harness
    foreign = _container(stubs, "deerflow-mi-postgres", state_dir="/elsewhere/.deer-flow/multi-instance")

    result = run("up", "--skip-install", "--no-nginx")

    assert result.returncode != 0
    assert "/elsewhere/.deer-flow/multi-instance" in result.stderr
    assert foreign.is_dir()
    commands = (stubs / "docker.log").read_text()
    assert "docker rm" not in commands and "docker run" not in commands

    down = run("down")

    assert foreign.is_dir(), "down must not remove another harness's container either"
    assert "docker rm" not in (stubs / "docker.log").read_text(), down.stdout + down.stderr


def test_up_replaces_its_own_stale_containers_with_their_volumes(stubbed_harness):
    stubs, state, ports, run = stubbed_harness
    _container(stubs, "deerflow-mi-redis", state_dir=str(state))
    (stubs / f"busy-from-{ports['b']}").write_text("2", encoding="utf-8")  # stop after A so the test stays short

    run("up", "--skip-install", "--no-nginx")

    log = (stubs / "docker.log").read_text().splitlines()
    first_run = next(i for i, line in enumerate(log) if line.startswith("docker run"))
    assert "docker rm -f -v deerflow-mi-redis" in log[:first_run]
    labelled = [line for line in log if line.startswith("docker run")]
    assert all(f"--label deerflow.harness.state-dir={state}" in line for line in labelled), labelled
