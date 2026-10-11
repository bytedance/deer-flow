"""Invalid ``mcpLifecycle`` must abort lazy MCP initialization deterministically.

An unverifiable ledger can never be published, so a retry loop that keeps
re-running discovery is both a hang and a resource leak. These tests drive the
real ``get_cached_mcp_tools()`` entry in a subprocess (with a timeout) so a
regression cannot hang the pytest worker.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_CONFIG = {"mcpServers": {"A": {"enabled": True, "type": "stdio", "command": "npx"}}, "skills": {}}

# Aborts on an unverifiable ledger before discovery: the fake discovery counter
# must stay at 0, and a pre-existing durable binding must be retired.
_INVALID_PROGRAM = textwrap.dedent(
    """
    import json
    import os
    from pathlib import Path

    import deerflow.mcp.tools as tools_module
    from deerflow.mcp import cache as cache_module
    from deerflow.mcp import session_pool as session_pool_module

    cfg = Path(os.environ["DEER_FLOW_EXTENSIONS_CONFIG_PATH"])
    pool = session_pool_module.get_session_pool()
    pool.ensure_binding("A", "durable-fp", domain="deployment")

    calls = {"n": 0}

    async def _fake_get_mcp_tools(**_kwargs):
        calls["n"] += 1
        return ["should-not-publish"]

    tools_module.get_mcp_tools = _fake_get_mcp_tools

    result = cache_module.get_cached_mcp_tools()
    print(json.dumps({
        "result": len(result),
        "discovery_calls": calls["n"],
        "old_pool_retired": pool._retired,
        "pool_singleton_is_none": session_pool_module._pool is None,
    }))
    """
)

# The same call must recover once the ledger is fixed, without a restart.
_RECOVERY_PROGRAM = textwrap.dedent(
    """
    import json
    import os
    from pathlib import Path

    import deerflow.mcp.tools as tools_module
    from deerflow.mcp import cache as cache_module

    cfg = Path(os.environ["DEER_FLOW_EXTENSIONS_CONFIG_PATH"])
    calls = {"n": 0}

    async def _fake_get_mcp_tools(**_kwargs):
        calls["n"] += 1
        return ["tool"]

    tools_module.get_mcp_tools = _fake_get_mcp_tools

    first = cache_module.get_cached_mcp_tools()
    first_calls = calls["n"]

    cfg.write_text(os.environ["DEER_FLOW_VALID_CONFIG"], encoding="utf-8")
    second = cache_module.get_cached_mcp_tools()

    print(json.dumps({
        "first": len(first),
        "first_calls": first_calls,
        "second": len(second),
        "total_calls": calls["n"],
    }))
    """
)


def _run_program(program: str, cfg: Path) -> dict:
    env = os.environ.copy()
    env["DEER_FLOW_EXTENSIONS_CONFIG_PATH"] = str(cfg)
    env["DEER_FLOW_VALID_CONFIG"] = json.dumps(_CONFIG)
    try:
        completed = subprocess.run(
            [sys.executable, "-c", program],
            cwd=str(Path(__file__).resolve().parent.parent),
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        pytest.fail("get_cached_mcp_tools() did not terminate on an invalid mcpLifecycle")
    assert completed.returncode == 0, f"worker failed ({completed.returncode})\n--- stdout ---\n{completed.stdout}\n--- stderr ---\n{completed.stderr}"
    return json.loads(completed.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize(
    "ledger",
    [
        {"version": 2, "servers": {}},
        {"version": 1, "servers": {"A": "a" * 32 + "\n"}},
    ],
)
def test_invalid_lifecycle_aborts_lazy_initialization_without_discovery(ledger, tmp_path):
    cfg = tmp_path / "extensions_config.json"
    cfg.write_text(json.dumps({**_CONFIG, "mcpLifecycle": ledger}), encoding="utf-8")

    payload = _run_program(_INVALID_PROGRAM, cfg)

    assert payload["result"] == 0
    assert payload["discovery_calls"] == 0  # discovery is never entered
    assert payload["old_pool_retired"] is True  # stale bindings are not reused
    assert payload["pool_singleton_is_none"] is True


def test_invalid_lifecycle_recovers_after_the_config_is_fixed(tmp_path):
    cfg = tmp_path / "extensions_config.json"
    cfg.write_text(json.dumps({**_CONFIG, "mcpLifecycle": {"version": 2, "servers": {}}}), encoding="utf-8")

    payload = _run_program(_RECOVERY_PROGRAM, cfg)

    assert payload["first"] == 0
    assert payload["first_calls"] == 0
    assert payload["second"] == 1  # valid config initializes normally
    assert payload["total_calls"] == 1
