# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Artifact storage manager for tool result file offloading."""

import json
import os
import re
from pathlib import Path
from typing import Literal

from src.compression.models import CompressionInput, ToolResultCompression


class ArtifactStorageManager:
    """
    Manages file offloading for raw tool outputs.

    Implements deterministic filename generation and ensures all raw
    outputs are saved to disk regardless of usefulness.
    """

    def __init__(self, base_path: str | Path = "research_artifacts"):
        """
        Initialize the artifact storage manager.

        Args:
            base_path: Base directory for artifact storage.
        """
        self.base_path = Path(base_path)

    def _sanitize_filename_component(self, component: str) -> str:
        """
        Sanitize a filename component to be safe and deterministic.

        Converts to lowercase, replaces spaces with underscores, and removes
        special characters that are problematic in filenames.

        Args:
            component: String to sanitize

        Returns:
            Sanitized string safe for use in filenames
        """
        # Convert to lowercase
        component = component.lower()

        # Replace spaces and hyphens with underscores
        component = component.replace(" ", "_").replace("-", "_")

        # Remove any characters that aren't alphanumeric, underscores, or dots
        component = re.sub(r"[^a-z0-9_.]", "", component)

        # Collapse multiple consecutive underscores
        component = re.sub(r"_+", "_", component)

        # Remove leading/trailing underscores
        component = component.strip("_")

        return component

    def _generate_filename(
        self,
        plan_title: str,
        step_id: str,
        step_title: str,
        tool_name: str,
        extension: Literal["json", "txt"] = "json",
    ) -> str:
        """
        Generate a deterministic filename for a tool result artifact.

        Format: {plan_title}__step{step_id}_{step_title}__{tool_name}.{ext}

        The filename is deterministic and never depends on LLM-generated text.

        Args:
            plan_title: Title of the research plan
            step_id: ID of the current step
            step_title: Title of the current step
            tool_name: Name of the tool that was called
            extension: File extension (json or txt)

        Returns:
            Deterministic filename following the required convention
        """
        sanitized_plan = self._sanitize_filename_component(plan_title)
        sanitized_step_title = self._sanitize_filename_component(step_title)
        sanitized_tool_name = self._sanitize_filename_component(tool_name)

        filename = (
            f"{sanitized_plan}__step{step_id}_{sanitized_step_title}__"
            f"{sanitized_tool_name}.{extension}"
        )

        return filename

    def _get_plan_directory(self, plan_title: str) -> Path:
        """
        Get the directory path for a plan's artifacts.

        Creates the directory if it doesn't exist.

        Args:
            plan_title: Title of the research plan

        Returns:
            Path to the plan's artifact directory
        """
        sanitized_plan = self._sanitize_filename_component(plan_title)
        plan_dir = self.base_path / sanitized_plan

        plan_dir.mkdir(parents=True, exist_ok=True)

        return plan_dir

    def save_raw_output(
        self,
        input_data: CompressionInput,
        raw_output: str,
    ) -> str:
        """
        Save the raw tool output to disk.

        This always runs, even if is_useful == false.

        Args:
            input_data: Compression input containing context
            raw_output: Raw output from the tool

        Returns:
            Relative path to the saved file (for injection into conversation)
        """
        plan_dir = self._get_plan_directory(input_data.plan_title)

        # Try to parse as JSON for pretty printing, otherwise save as text
        try:
            parsed = json.loads(raw_output)
            content = json.dumps(parsed, indent=2, ensure_ascii=False)
            extension = "json"
        except (json.JSONDecodeError, TypeError):
            content = raw_output
            extension = "txt"

        filename = self._generate_filename(
            plan_title=input_data.plan_title,
            step_id=input_data.step_id,
            step_title=input_data.step_title,
            tool_name=input_data.tool_name,
            extension=extension,
        )

        file_path = plan_dir / filename

        # Write the raw output
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)

        # Return relative path from base_path
        relative_path = file_path.relative_to(self.base_path.parent)
        return str(relative_path)

    def save_compression_metadata(
        self,
        input_data: CompressionInput,
        compression: ToolResultCompression,
        artifact_file: str,
    ) -> None:
        """
        Save the compression metadata alongside the raw output.

        This stores the compression result as a separate JSON file for
        debugging and analysis.

        Args:
            input_data: Compression input containing context
            compression: The compression result
            artifact_file: Path to the raw output artifact file
        """
        plan_dir = self._get_plan_directory(input_data.plan_title)

        filename = self._generate_filename(
            plan_title=input_data.plan_title,
            step_id=input_data.step_id,
            step_title=input_data.step_title,
            tool_name=input_data.tool_name,
            extension="meta.json",
        )

        metadata_path = plan_dir / filename

        metadata = {
            "summary_title": compression.summary_title,
            "summary": compression.summary,
            "extraction": compression.extraction,
            "is_useful": compression.is_useful,
            "artifact_file": artifact_file,
            "plan_title": input_data.plan_title,
            "step_id": input_data.step_id,
            "step_title": input_data.step_title,
            "step_description": input_data.step_description,
            "tool_name": input_data.tool_name,
        }

        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
