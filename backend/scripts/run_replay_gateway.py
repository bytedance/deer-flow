"""Start a hermetic *replay* gateway for the full-stack (Layer 2) e2e.

Builds an ephemeral config that points the model at ``ReplayChatModel`` + a
recorded fixture, then runs uvicorn — no API key, deterministic. Used as a
Playwright ``webServer`` (see ``frontend/playwright.real-backend.config.ts``) and
runnable standalone for debugging::

    uv run python scripts/run_replay_gateway.py --port 8011

``tests/`` is put on the path so the config ``use: replay_provider:ReplayChatModel``
resolves; ``GATEWAY_CORS_ORIGINS`` is set so the frontend on :3000 can talk to it.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "tests"))  # replay_provider + build_config_yaml live here


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8011)
    parser.add_argument("--fixture", default=str(_BACKEND / "tests" / "fixtures" / "replay" / "write_read_file.ultra.json"))
    parser.add_argument("--cors", default="http://localhost:3000")
    args = parser.parse_args()

    from _replay_fixture import REPLAY_MODEL_BLOCK, build_config_yaml, prepare_hermetic_extras

    home = Path(tempfile.mkdtemp(prefix="replay-gw-"))
    cfg = home / "config.yaml"
    cfg.write_text(build_config_yaml(model_block=REPLAY_MODEL_BLOCK, home=home), encoding="utf-8")

    os.environ.setdefault("DEER_FLOW_HOME", str(home))
    os.environ["DEER_FLOW_CONFIG_PATH"] = str(cfg)
    os.environ["DEER_FLOW_EXTENSIONS_CONFIG_PATH"] = str(prepare_hermetic_extras(home))
    os.environ["DEERFLOW_REPLAY_FIXTURE"] = args.fixture
    os.environ.setdefault("AUTH_JWT_SECRET", "ci-replay-secret")
    os.environ["GATEWAY_CORS_ORIGINS"] = args.cors
    # Child / dynamic imports (resolve_class) search PYTHONPATH too.
    os.environ["PYTHONPATH"] = os.pathsep.join(p for p in (str(_BACKEND), str(_BACKEND / "tests"), os.environ.get("PYTHONPATH", "")) if p)

    import uvicorn

    print(f"[replay-gw] config={cfg} fixture={args.fixture} cors={args.cors} port={args.port}", flush=True)
    uvicorn.run("app.gateway.app:app", host="127.0.0.1", port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
