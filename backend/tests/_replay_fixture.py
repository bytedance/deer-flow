"""Shared config + gateway-drive helpers for the record/replay e2e.

Record (``scripts/record_gateway.py`` + ``scripts/build_fixture_from_jsonl.py``)
and replay (``tests/test_replay_golden.py``)
MUST drive the gateway through an identical, prompt-affecting config — otherwise
the system prompt differs and the recorded input hashes never match on replay.
Centralising the config builder + drive loop here makes that identity hold by
construction; only the ``models[].use`` block differs (real model vs
``ReplayChatModel``).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path

# mode -> (thinking_enabled, is_plan_mode, subagent_enabled). Mirrors the
# frontend mapping in core/threads/hooks.ts.
MODE_CONTEXT: dict[str, tuple[bool, bool, bool]] = {
    "flash": (False, False, False),
    "thinking": (True, False, False),
    "pro": (True, True, False),
    # thinking_enabled mirrors the frontend `context.mode !== "flash"` (hooks.ts),
    # so ultra is thinking-enabled too.
    "ultra": (True, True, True),
}

# The replay model block: same model NAME as recording (so nothing in the prompt
# shifts), only ``use`` swapped to the deterministic replay provider.
REPLAY_MODEL_BLOCK = """\
  - name: scenario-model
    display_name: Scenario Model
    use: replay_provider:ReplayChatModel
    model: replay
    supports_thinking: true"""


def real_model_block(model: str) -> str:
    return f"""\
  - name: scenario-model
    display_name: Scenario Model
    use: langchain_openai:ChatOpenAI
    model: {model}
    api_key: $OPENAI_API_KEY
    base_url: $OPENAI_API_BASE"""


def build_config_yaml(*, model_block: str, home: Path) -> str:
    """Full gateway config. Only ``model_block`` varies between record/replay.

    Everything that shapes the system prompt is pinned so record, replay, and CI
    produce byte-identical prompts regardless of the machine:
    - sandbox / tool_groups / tools — fixed here
    - skills — pointed at an empty ``<home>/skills`` so filesystem skills (incl.
      gitignored custom skills present only on a dev box) never leak into the
      prompt. Pair with an empty ``extensions_config.json`` (no MCP) via
      :func:`prepare_hermetic_extras`.
    - memory / summarization — disabled (background, non-deterministic timing)
    """
    return f"""\
log_level: warning
models:
{model_block}
sandbox:
  use: deerflow.sandbox.local:LocalSandboxProvider
skills:
  path: {home / "skills"}
  container_path: /mnt/skills
tool_groups:
  - name: file:read
  - name: file:write
tools:
  - name: ls
    group: file:read
    use: deerflow.sandbox.tools:ls_tool
  - name: read_file
    group: file:read
    use: deerflow.sandbox.tools:read_file_tool
  - name: write_file
    group: file:write
    use: deerflow.sandbox.tools:write_file_tool
# Memory + summarization make background / debounced model calls whose timing is
# non-deterministic; disable them so record and replay see the same model-call
# set. Title stays enabled, but the default title.model_name: null path is a
# local state update rather than a recorded model call.
memory:
  enabled: false
  injection_enabled: false
summarization:
  enabled: false
agents_api:
  enabled: true
database:
  backend: sqlite
  sqlite_dir: {home / "db"}
"""


def prepare_hermetic_extras(home: Path) -> Path:
    """Create the empty skills tree + an empty extensions_config.json so the
    system prompt has no environment-dependent skills/MCP content.

    Returns the extensions-config path; the caller must point
    ``DEER_FLOW_EXTENSIONS_CONFIG_PATH`` at it. Call before starting the gateway.
    """
    (home / "skills" / "public").mkdir(parents=True, exist_ok=True)
    (home / "skills" / "custom").mkdir(parents=True, exist_ok=True)
    extensions = home / "extensions_config.json"
    extensions.write_text(json.dumps({"mcpServers": {}, "skills": {}}), encoding="utf-8")
    return extensions


@dataclass(frozen=True)
class ReplayRunResult:
    """Captured replay run with raw events for semantic assertions."""

    thread_id: str
    events: list[dict]
    event_shapes: list[dict]


def _parse_sse_events(resp) -> list[dict]:
    """Parse an SSE response without committing volatile payload values."""

    events: list[dict] = []
    current: str | None = None
    for line in resp.iter_lines():
        if line.startswith("event:"):
            current = line[len("event:") :].strip()
        elif line.startswith("data:"):
            raw = line[len("data:") :].strip()
            try:
                data = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                data = {"_raw": raw[:200]}
            events.append({"event": current, "data": data})
    return events


def _sse_event_shapes(events: list[dict]) -> list[dict]:
    """Reduce parsed SSE events to event names and top-level data keys.

    Snapshots the *shape* of the stream, not volatile values, so the golden is
    stable across runs while still catching event-sequence / payload-shape drift.
    """
    return [
        {
            "event": event["event"],
            "keys": sorted(event["data"].keys()) if isinstance(event["data"], dict) else None,
        }
        for event in events
    ]


def drive_gateway(app, *, prompt: str, context: dict, stream_mode: list[str] | None = None) -> ReplayRunResult:
    """Register -> create thread -> POST /runs/stream; capture raw + shape events.

    This is the exact wire path the React frontend uses (LangGraph SDK), driven
    in-process via Starlette's TestClient with the real auth flow.
    """
    from starlette.testclient import TestClient

    with TestClient(app) as client:
        reg = client.post(
            "/api/v1/auth/register",
            json={"email": f"e2e-{uuid.uuid4().hex[:8]}@example.com", "password": "very-strong-password-123"},
        )
        assert reg.status_code == 201, reg.text
        csrf = client.cookies.get("csrf_token")
        assert csrf, "register must set csrf_token cookie"

        thread_id = str(uuid.uuid4())
        created = client.post("/api/threads", json={"thread_id": thread_id, "metadata": {}}, headers={"X-CSRF-Token": csrf})
        assert created.status_code == 200, created.text

        body = {
            "assistant_id": "lead_agent",
            "input": {"messages": [{"role": "user", "content": prompt}]},
            # Keep replay close to the Gateway default. A tighter limit can
            # produce false golden drift when protocol-neutral middleware adds
            # graph steps without changing the streamed SSE contract.
            "config": {"recursion_limit": 100},
            "context": context,
            "stream_mode": stream_mode or ["values"],
        }
        with client.stream("POST", f"/api/threads/{thread_id}/runs/stream", json=body, headers={"X-CSRF-Token": csrf}) as resp:
            assert resp.status_code == 200, resp.read().decode()
            events = _parse_sse_events(resp)
            return ReplayRunResult(
                thread_id=thread_id,
                events=events,
                event_shapes=_sse_event_shapes(events),
            )
