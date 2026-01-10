# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Artifact retrieval tool for accessing compressed tool results."""

import json
import logging
import os
from pathlib import Path
from typing import Annotated

from langchain_core.tools import tool

from src.config.configuration import Configuration
from src.config.loader import get_str_env

logger = logging.getLogger(__name__)


# Default artifact path from config or environment
DEFAULT_ARTIFACT_PATH = get_str_env("ARTIFACT_STORAGE_PATH", "research_artifacts")


@tool
def read_artifact(
    artifact_path: Annotated[
        str, "The relative path to the artifact file (e.g., 'research_artifacts/plan_name/stepX_title__tool_name.json')"
    ],
) -> str:
    """
    Read the full raw output from a compressed tool result artifact.

    Use this tool when you need to access the complete, uncompressed data from a previous tool call.
    The compressed summary in the conversation should provide enough context for most tasks,
    but use this tool when you need to:
    - Examine specific details not mentioned in the summary
    - Verify or quote directly from the source
    - Perform detailed analysis that requires the full dataset

    The artifact_path is provided in the compressed summary as 'artifact_file'.
    """
    try:
        # Convert relative path to absolute if needed
        artifact_path = Path(artifact_path)
        if not artifact_path.is_absolute():
            # If path doesn't start with the default artifact path, prepend it
            if not str(artifact_path).startswith(DEFAULT_ARTIFACT_PATH):
                artifact_path = Path(DEFAULT_ARTIFACT_PATH) / artifact_path

        # Check if file exists
        if not artifact_path.exists():
            return f"Error: Artifact file not found at {artifact_path}"

        # Read file content
        with open(artifact_path, "r", encoding="utf-8") as f:
            content = f.read()

        # If file is JSON, return it; otherwise return as-is
        if artifact_path.suffix == ".json":
            try:
                parsed = json.loads(content)
                # Format nicely for readability
                return json.dumps(parsed, indent=2, ensure_ascii=False)
            except json.JSONDecodeError:
                # Not valid JSON, return as text
                pass

        return content

    except Exception as e:
        logger.error(f"Error reading artifact file {artifact_path}: {e}")
        return f"Error reading artifact file: {str(e)}"


@tool
def list_artifacts(
    plan_name: Annotated[
        str, "The name of the plan to list artifacts for (e.g., 'research_plan_name')"
    ] = "",
) -> str:
    """
    List all artifact files for a specific plan or all plans.

    Use this tool to discover what artifact files are available.
    If plan_name is empty, lists all artifacts across all plans.
    """
    try:
        artifact_base = Path(DEFAULT_ARTIFACT_PATH)

        if not artifact_base.exists():
            return f"No artifacts directory found at {DEFAULT_ARTIFACT_PATH}"

        # If plan_name specified, list only that plan's artifacts
        if plan_name:
            plan_dir = artifact_dir = artifact_base / _sanitize_path_component(plan_name)
            if not plan_dir.exists():
                return f"No artifacts found for plan: {plan_name}"
            artifacts = list(plan_dir.glob("*"))
        else:
            # List all artifacts from all plans
            artifacts = list(artifact_base.glob("**/*.*"))

        # Filter out directories and metadata files
        artifact_files = [
            a for a in artifacts if a.is_file() and not a.name.endswith(".meta.json")
        ]

        if not artifact_files:
            return "No artifact files found."

        # Build result
        result_lines = []
        for artifact_file in sorted(artifact_files):
            # Get relative path from base
            rel_path = artifact_file.relative_to(artifact_base.parent)
            size_kb = artifact_file.stat().st_size / 1024
            result_lines.append(f"- {rel_path} ({size_kb:.1f} KB)")

        return "\n".join(result_lines)

    except Exception as e:
        logger.error(f"Error listing artifacts: {e}")
        return f"Error listing artifacts: {str(e)}"


def _sanitize_path_component(component: str) -> str:
    """Sanitize a path component for safe filesystem access."""
    # Similar to ArtifactStorageManager._sanitize_filename_component
    import re

    component = component.lower().replace(" ", "_").replace("-", "_")
    component = re.sub(r"[^a-z0-9_.]", "", component)
    component = re.sub(r"_+", "_", component)
    return component.strip("_")
