"""Gateway import regression tests."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _gateway_import_env() -> dict[str, str]:
    backend_root = Path(__file__).resolve().parents[1]
    harness_root = backend_root / "packages" / "harness"
    python_path_entries = [str(backend_root), str(harness_root)]
    if existing_python_path := os.environ.get("PYTHONPATH"):
        python_path_entries.append(existing_python_path)
    return {**os.environ, "PYTHONPATH": os.pathsep.join(python_path_entries)}


def test_gateway_app_imports_first_without_subagent_import_cycle() -> None:
    """The replay gateway imports app.gateway.app in a clean process."""
    result = subprocess.run(
        [sys.executable, "-c", "from app.gateway.app import app"],
        capture_output=True,
        text=True,
        env=_gateway_import_env(),
    )
    assert result.returncode == 0, result.stderr


def test_title_middleware_imports_without_message_identity_cycle() -> None:
    """A middleware module must be importable as the process's first import.

    ``message_identity`` reaching back into ``agents.middlewares`` closed a cycle
    (middleware -> deerflow.runtime -> worker -> events -> middleware) that only
    stayed hidden while some earlier import happened to break it first. Running
    ``tests/test_title_generation.py`` on its own was enough to hit it.
    """
    result = subprocess.run(
        [sys.executable, "-c", "from deerflow.agents.middlewares.title_middleware import TitleMiddleware; print(TitleMiddleware.__name__)"],
        capture_output=True,
        text=True,
        env=_gateway_import_env(),
    )
    assert result.returncode == 0, result.stderr
    assert "TitleMiddleware" in result.stdout


def test_message_identity_imports_standalone() -> None:
    """The seq-lookup identity helper must not require the agent package first."""
    result = subprocess.run(
        [sys.executable, "-c", "from deerflow.runtime.events.message_identity import message_identity; print(message_identity({'id': 'x__user', 'type': 'human'}))"],
        capture_output=True,
        text=True,
        env=_gateway_import_env(),
    )
    assert result.returncode == 0, result.stderr
    assert "message:x" in result.stdout


def test_subagent_package_public_executor_exports_are_lazy_importable() -> None:
    """The package-level executor exports must not re-enter their own import."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from deerflow.subagents import SubagentExecutor, SubagentResult; print(SubagentExecutor.__name__, SubagentResult.__name__)",
        ],
        capture_output=True,
        text=True,
        env=_gateway_import_env(),
    )
    assert result.returncode == 0, result.stderr
    assert "SubagentExecutor SubagentResult" in result.stdout


def test_workspace_changes_package_imports_standalone() -> None:
    """The workspace-changes package must import as the process's first import.

    ``workspace_changes.api`` reads ``deerflow.runtime.user_context`` for the
    ``AUTO`` sentinel, which runs ``deerflow.runtime``'s package init and imports
    ``.runs`` -> ``worker`` -> ``deerflow.workspace_changes`` again. Importing
    ``.api`` before this package bound its own names made that re-entrant import
    fail with ImportError whenever ``deerflow.runtime`` had not been imported
    yet.
    """
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import deerflow.workspace_changes as w; print(w.scan_workspace_roots.__name__, w.get_workspace_changes_response.__name__)",
        ],
        capture_output=True,
        text=True,
        env=_gateway_import_env(),
    )
    assert result.returncode == 0, result.stderr
    assert "scan_workspace_roots get_workspace_changes_response" in result.stdout
