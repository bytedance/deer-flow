"""Pytest scaffold for the DeerFlow Monocle test suite.

Enables Monocle tracing, loads the repo `.env`, and exposes ``run_deerflow`` --
the single entry the live test uses to drive the agent under instrumentation.
"""
import uuid
from pathlib import Path

from dotenv import load_dotenv
from monocle_apptrace import setup_monocle_telemetry

HERE = Path(__file__).resolve().parent
TRACES = HERE / "traces"
REPO_ROOT = HERE.parent.parent  # tests/monocle/ -> tests/ -> repo root

setup_monocle_telemetry(workflow_name="deer-flow")
load_dotenv(REPO_ROOT / ".env")


def run_deerflow(message: str) -> str:
    """Run the DeerFlow agent once and return its final response text."""
    from deerflow.client import DeerFlowClient

    client = DeerFlowClient(
        config_path=str(REPO_ROOT / "config.yaml"),
        model_name="gpt-4o",
        subagent_enabled=True,
    )
    return client.chat(message, thread_id=f"monocle-test-{uuid.uuid4().hex[:8]}")
