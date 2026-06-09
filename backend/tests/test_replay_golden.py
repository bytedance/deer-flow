"""Layer 1 of the record/replay e2e: replay a recorded trace through the **real
gateway** with a deterministic ``ReplayChatModel`` (no API key, no network) and
assert the streamed SSE event sequence matches a committed golden.

This catches backend protocol drift: if a change alters the shape/sequence of
SSE the gateway emits for the recorded scenario, this test goes red. The replay
model serves the recorded assistant turns by input hash, so the agent graph
(write_file -> auto-title -> read_file -> final answer) reproduces offline.

Fixtures are produced by ``scripts/record_gateway.py`` +
``scripts/build_fixture_from_jsonl.py`` (manual, needs a key).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from _replay_fixture import REPLAY_MODEL_BLOCK, build_config_yaml, drive_gateway, prepare_hermetic_extras

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "replay"


def _reset_process_singletons(monkeypatch: pytest.MonkeyPatch) -> None:
    """Invalidate process-wide caches so the test-only config/home take effect.

    Same set the real-server e2e resets (see test_setup_agent_http_e2e_real_server).
    """
    from deerflow.config import app_config as app_config_module
    from deerflow.config import paths as paths_module
    from deerflow.persistence import engine as engine_module

    for module, attr in (
        (app_config_module, "_app_config"),
        (app_config_module, "_app_config_path"),
        (app_config_module, "_app_config_mtime"),
        (paths_module, "_paths_singleton"),
        (engine_module, "_engine"),
        (engine_module, "_session_factory"),
    ):
        monkeypatch.setattr(module, attr, None, raising=False)


@pytest.mark.no_auto_user
def test_replay_write_read_file_ultra_matches_golden(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    scenario, mode = "write_read_file", "ultra"
    fixture_path = FIXTURE_DIR / f"{scenario}.{mode}.json"
    events_path = FIXTURE_DIR / f"{scenario}.{mode}.events.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("DEER_FLOW_HOME", str(home))
    monkeypatch.setenv("DEERFLOW_REPLAY_FIXTURE", str(fixture_path))

    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(build_config_yaml(model_block=REPLAY_MODEL_BLOCK, home=home), encoding="utf-8")
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(cfg_path))
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(prepare_hermetic_extras(home)))

    _reset_process_singletons(monkeypatch)
    from deerflow.config import app_config as app_config_module

    cfg = app_config_module.get_app_config()
    cfg.database.sqlite_dir = str(home / "db")

    # Fail loud on a replay miss. The gateway swallows a hash-miss into a normal
    # assistant error message, so the SSE *shapes* below stay green on a stale
    # fixture — the miss list is the only reliable signal at this layer.
    import replay_provider

    from app.gateway.app import create_app

    replay_provider.reset_replay_misses()

    events = drive_gateway(create_app(), prompt=fixture["prompt"], context=fixture["context"])

    assert events, "replay produced no SSE events"
    assert events[0]["event"] == "metadata", f"first event should be metadata, got {events[0]!r}"
    assert events[-1]["event"] == "end", f"last event should be end (run completed), got {events[-1]!r}"

    misses = replay_provider.replay_misses()
    assert not misses, f"replay miss ({len(misses)}): the fixture is stale vs the current system prompt or agent graph. Re-record it (see backend/docs/REPLAY_E2E.md). Missed hashes: {misses}"

    # Regenerate the committed golden after re-recording the fixture:
    #   DEERFLOW_WRITE_GOLDEN=1 uv run pytest tests/test_replay_golden.py
    if os.environ.get("DEERFLOW_WRITE_GOLDEN"):
        events_path.write_text(json.dumps({"scenario": scenario, "mode": mode, "events": events}, ensure_ascii=False, indent=2), encoding="utf-8")
        return

    golden = json.loads(events_path.read_text(encoding="utf-8"))["events"]
    # Guards backend SSE protocol drift: the event name + payload-key sequence
    # must match the committed golden. (Replay divergence is caught by the miss
    # assertion above, not here — a swallowed miss keeps the shapes identical.)
    assert events == golden, f"SSE event-shape sequence drifted from the golden.\ngot  ({len(events)}): {[e['event'] for e in events]}\nwant ({len(golden)}): {[e['event'] for e in golden]}"
