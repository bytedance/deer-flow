"""LangChain tool for visualizing steel-structure originData with fea-worker."""

from __future__ import annotations

import json
from pathlib import Path

from langchain.tools import ToolRuntime, tool
from langgraph.typing import ContextT

from deerflow.agents.thread_state import ThreadState
from deerflow.sandbox.tools import get_thread_data

from .service import visualize_origin_data


def _resolve_outputs_dir(runtime: ToolRuntime[ContextT, ThreadState]) -> Path:
    thread_data = get_thread_data(runtime)
    outputs_path = thread_data.get("outputs_path") if thread_data else None
    if not outputs_path:
        raise ValueError("Thread outputs path is not available in runtime state")
    return Path(outputs_path)


@tool("visualize_steel_structure", parse_docstring=True)
def visualize_steel_structure(
    runtime: ToolRuntime[ContextT, ThreadState],
    origin_data_json: str,
    model_name: str | None = None,
    artifact_prefix: str | None = None,
) -> str:
    """Build VSFX/CDA/properties artifacts from a complete steel-structure originData JSON string.

    Use this after you have already written a complete `originData` JSON document that follows the iCAD steel-structure schema.
    The tool sends `origin_data_json` to fea-worker, writes the returned `.vsfx`, `.cda.json`, and `.properties.json`
    artifacts into the current thread outputs directory, and returns the file paths plus APF issue details.

    Args:
        origin_data_json: Complete `originData` JSON string for one steel-structure model.
        model_name: Optional display name for the model sent to the worker.
        artifact_prefix: Optional filename prefix for the output artifacts. If omitted, the tool derives one from `model_name`.
    """

    result = visualize_origin_data(
        origin_data_json=origin_data_json,
        model_name=model_name,
        output_dir=_resolve_outputs_dir(runtime),
        artifact_prefix=artifact_prefix,
    )
    return json.dumps(
        {
            "modelName": result["model_name"],
            "artifacts": {
                "vsfx": result["artifacts"]["vsfx_path"],
                "cdaJson": result["artifacts"]["cda_json_path"],
                "propertiesJson": result["artifacts"]["properties_json_path"],
            },
            "apfIssues": result["apf_issues"],
            "apfIssueSummary": result["apf_issue_summary"],
        },
        ensure_ascii=False,
    )
