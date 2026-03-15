#!/usr/bin/env python
"""Start the LangGraph API server with persistent storage.

``langgraph dev`` forces an in-memory database for both its internal state
(threads, runs) and the graph checkpointer, which means conversation state is
lost on every restart -- even when a custom checkpointer is configured in
``langgraph.json`` (upstream: langchain-ai/langgraph#5790).

This script calls ``run_server`` directly with a file-backed SQLite database
for internal API state and passes the ``checkpointer`` config from
``langgraph.json`` so that the custom checkpointer is respected.

Usage (from the ``backend/`` directory):
    uv run python ../scripts/start_langgraph.py [--host HOST] [--port PORT]
        [--no-reload] [--no-browser] [--allow-blocking]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Start LangGraph server with persistent storage")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2024)
    parser.add_argument("--no-reload", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--allow-blocking", action="store_true")
    parser.add_argument("--config", default="langgraph.json")
    args = parser.parse_args()

    # Load langgraph.json
    config_path = Path(args.config)
    if not config_path.exists():
        print(f"Config file not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    with open(config_path) as f:
        config_json = json.load(f)

    # Add current directory and dependencies to sys.path (same as langgraph dev)
    cwd = os.getcwd()
    if cwd not in sys.path:
        sys.path.append(cwd)
    for dep in config_json.get("dependencies", []):
        dep_path = Path(cwd) / dep
        if dep_path.is_dir() and dep_path.exists() and str(dep_path) not in sys.path:
            sys.path.append(str(dep_path))

    try:
        from langgraph_api.cli import run_server
    except ImportError:
        print(
            "langgraph-api is not installed. "
            'Install it with: uv add "langgraph-cli[inmem]"',
            file=sys.stderr,
        )
        sys.exit(1)

    # Resolve persistent database path.
    # DEER_FLOW_HOME is the standard data directory; fall back to .deer-flow/
    deer_flow_home = os.environ.get("DEER_FLOW_HOME", ".deer-flow")
    os.makedirs(deer_flow_home, exist_ok=True)
    db_path = os.path.join(deer_flow_home, "langgraph_api.db")

    graphs = config_json.get("graphs", {})
    checkpointer = config_json.get("checkpointer")

    run_server(
        host=args.host,
        port=args.port,
        reload=not args.no_reload,
        graphs=graphs,
        open_browser=not args.no_browser,
        allow_blocking=args.allow_blocking,
        env=config_json.get("env"),
        store=config_json.get("store"),
        auth=config_json.get("auth"),
        http=config_json.get("http"),
        ui=config_json.get("ui"),
        ui_config=config_json.get("ui_config"),
        webhooks=config_json.get("webhooks"),
        checkpointer=checkpointer,
        # Use file-backed SQLite instead of :memory: so that internal API
        # state (threads, runs) survives restarts.
        __database_uri__=f"sqlite:///{db_path}",
    )


if __name__ == "__main__":
    main()
