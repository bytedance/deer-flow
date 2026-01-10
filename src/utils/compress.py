# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Compression utilities for tool result file offloading."""

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

logger = logging.getLogger(__name__)

# Initialize Jinja2 environment for prompts
_prompt_env = Environment(
    loader=FileSystemLoader(os.path.join(os.path.dirname(__file__), "../prompts")),
    autoescape=select_autoescape(),
    trim_blocks=True,
    lstrip_blocks=True,
)


def get_artifact_base_path(configurable_path: str | None = None) -> Path:
    """
    Get the base path for artifact storage.

    Args:
        configurable_path: Optional path from configuration

    Returns:
        Path to the artifact storage directory
    """
    # Use configured path or default
    path = configurable_path or os.environ.get(
        "ARTIFACT_STORAGE_PATH", "research_artifacts"
    )
    return Path(path)


def sanitize_filename_component(component: str) -> str:
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


def generate_artifact_filename(
    plan_title: str,
    step_id: str,
    step_title: str,
    tool_name: str,
    extension: str = "json",
) -> str:
    """
    Generate a deterministic filename for a tool result artifact.

    Format: {plan_title}__step{step_id}_{step_title}__{tool_name}.{ext}

    The filename is deterministic and never depends on LLM-generated text.
    Components are truncated to keep total filename under 100 characters.

    Args:
        plan_title: Title of the research plan
        step_id: ID of the current step
        step_title: Title of the current step
        tool_name: Name of the tool that was called
        extension: File extension (json or txt)

    Returns:
        Deterministic filename following the required convention
    """
    sanitized_plan = sanitize_filename_component(plan_title)
    sanitized_step_title = sanitize_filename_component(step_title)
    sanitized_tool_name = sanitize_filename_component(tool_name)

    # Apply length limits to prevent excessively long filenames
    # Target: max 100 chars total (conservative for filesystem compatibility)
    plan = sanitized_plan[:30]
    step = sanitized_step_title[:30]
    tool = sanitized_tool_name[:20]

    filename = f"{plan}__s{step_id}_{step}__{tool}.{extension}"

    # Fallback truncation if still too long (unlikely given limits above)
    if len(filename) > 100:
        step = sanitized_step_title[:20]
        plan = sanitized_plan[:40]
        filename = f"{plan}__s{step_id}_{step}__{tool}.{extension}"

    return filename


def get_plan_directory(plan_title: str, base_path: str | Path | None = None) -> Path:
    """
    Get the directory path for a plan's artifacts.

    Creates the directory if it doesn't exist.

    Args:
        plan_title: Title of the research plan
        base_path: Optional base path override

    Returns:
        Path to the plan's artifact directory
    """
    if base_path is None:
        base_path = get_artifact_base_path()
    else:
        base_path = Path(base_path)

    sanitized_plan = sanitize_filename_component(plan_title)
    plan_dir = base_path / sanitized_plan

    plan_dir.mkdir(parents=True, exist_ok=True)

    return plan_dir


def save_raw_output(
    plan_title: str,
    step_id: str,
    step_title: str,
    tool_name: str,
    raw_output: str,
    base_path: str | Path | None = None,
) -> str:
    """
    Save the raw tool output to disk.

    This always runs, even if is_useful == false.

    Args:
        plan_title: Title of the research plan
        step_id: ID of the current step
        step_title: Title of the current step
        tool_name: Name of the tool that was called
        raw_output: Raw output from the tool
        base_path: Optional base path override

    Returns:
        Relative path to the saved file (for injection into conversation)
    """
    plan_dir = get_plan_directory(plan_title, base_path)

    # Try to parse as JSON for pretty printing, otherwise save as text
    try:
        parsed = json.loads(raw_output)
        content = json.dumps(parsed, indent=2, ensure_ascii=False)
        extension = "json"
    except (json.JSONDecodeError, TypeError):
        content = raw_output
        extension = "txt"

    filename = generate_artifact_filename(
        plan_title=plan_title,
        step_id=step_id,
        step_title=step_title,
        tool_name=tool_name,
        extension=extension,
    )

    file_path = plan_dir / filename

    # Write the raw output
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)

    # Return relative path from base_path parent
    base = get_artifact_base_path() if base_path is None else Path(base_path)
    relative_path = file_path.relative_to(base.parent)
    return str(relative_path)


def save_compression_metadata(
    plan_title: str,
    step_id: str,
    step_title: str,
    tool_name: str,
    compression_result: dict[str, Any],
    artifact_file: str,
    base_path: str | Path | None = None,
) -> None:
    """
    Save the compression metadata alongside the raw output.

    This stores the compression result as a separate JSON file for
    debugging and analysis.

    Args:
        plan_title: Title of the research plan
        step_id: ID of the current step
        step_title: Title of the current step
        tool_name: Name of the tool that was called
        compression_result: The compression result dict
        artifact_file: Path to the raw output artifact file
        base_path: Optional base path override
    """
    plan_dir = get_plan_directory(plan_title, base_path)

    filename = generate_artifact_filename(
        plan_title=plan_title,
        step_id=step_id,
        step_title=step_title,
        tool_name=tool_name,
        extension="meta.json",
    )

    metadata_path = plan_dir / filename

    metadata = {
        "summary_title": compression_result.get("summary_title", ""),
        "summary": compression_result.get("summary", ""),
        "extraction": compression_result.get("extraction", []),
        "is_useful": compression_result.get("is_useful", True),
        "artifact_file": artifact_file,
        "plan_title": plan_title,
        "step_id": step_id,
        "step_title": step_title,
        "tool_name": tool_name,
    }

    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)


async def compress_tool_result(
    llm: BaseChatModel,
    plan_title: str,
    step_id: str,
    step_title: str,
    step_description: str,
    tool_name: str,
    raw_output: str,
    base_path: str | Path | None = None,
) -> dict[str, Any] | None:
    """
    Compress a tool result using an LLM and save the raw output to disk.

    This is the main entry point for the compression pipeline.

    Args:
        llm: The LLM to use for compression (should be a fast, cost-effective model)
        plan_title: Title of the research plan
        step_id: ID of the current step
        step_title: Title of the current step
        step_description: Description of the current step
        tool_name: Name of the tool that was called
        raw_output: Raw output from the tool
        base_path: Optional base path override

    Returns:
        dict with keys: summary_title, summary, extraction, artifact_file
        None if is_useful == false or compression fails

    Raises:
        json.JSONDecodeError: If the LLM returns invalid JSON
        ValueError: If the compression result fails validation
    """
    # Step 1: Save raw output to disk (always runs, even if compression fails)
    artifact_file = save_raw_output(
        plan_title=plan_title,
        step_id=step_id,
        step_title=step_title,
        tool_name=tool_name,
        raw_output=raw_output,
        base_path=base_path,
    )
    logger.info(f"Saved raw tool output to: {artifact_file}")

    # Step 2: Invoke LLM for compression
    try:
        compression_result = await _invoke_compression_llm(
            llm=llm,
            plan_title=plan_title,
            step_id=step_id,
            step_title=step_title,
            step_description=step_description,
            tool_name=tool_name,
            raw_output=raw_output,
        )
    except Exception as e:
        logger.error(f"Compression LLM invocation failed: {e}")
        # On compression failure, we still saved the raw output
        # Return None to skip injection but preserve the artifact
        return None

    # Step 3: Save compression metadata
    save_compression_metadata(
        plan_title=plan_title,
        step_id=step_id,
        step_title=step_title,
        tool_name=tool_name,
        compression_result=compression_result,
        artifact_file=artifact_file,
        base_path=base_path,
    )

    # Step 4: Return metadata for injection only if useful
    if compression_result.get("is_useful", True):
        return {
            "summary_title": compression_result.get("summary_title", ""),
            "summary": compression_result.get("summary", ""),
            "extraction": compression_result.get("extraction", []),
            "artifact_file": artifact_file,
        }
    else:
        logger.info("Tool result marked as not useful, skipping conversation injection")
        return None


async def _invoke_compression_llm(
    llm: BaseChatModel,
    plan_title: str,
    step_id: str,
    step_title: str,
    step_description: str,
    tool_name: str,
    raw_output: str,
) -> dict[str, Any]:
    """
    Invoke the LLM to compress the tool output.

    Args:
        llm: The LLM to use for compression
        plan_title: Title of the research plan
        step_id: ID of the current step
        step_title: Title of the current step
        step_description: Description of the current step
        tool_name: Name of the tool that was called
        raw_output: Raw output from the tool

    Returns:
        Parsed compression result dict with keys: summary_title, summary, extraction, is_useful

    Raises:
        json.JSONDecodeError: If the LLM returns invalid JSON
        ValueError: If the result fails validation
    """
    # Load the system prompt
    try:
        template = _prompt_env.get_template("compression.md")
        system_prompt = template.render()
    except Exception as e:
        logger.error(f"Failed to load compression prompt template: {e}")
        # Fallback to simple system prompt
        system_prompt = (
            "You are a compression specialist. Always respond with valid JSON."
        )

    # Create structured user message with context
    context_message = (
        f"# Tool Result Compression Context\n\n"
        f"## Research Context\n"
        f"- **Research Plan**: {plan_title}\n"
        f"- **Current Step**: {step_title} (Step {step_id})\n"
        f"- **Step Description**: {step_description}\n"
        f"- **Tool Used**: {tool_name}\n\n"
        f"## Tool Output\n\n```\n{raw_output[:50000]}\n```"
    )

    # Prepare messages
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=context_message),
    ]

    # Invoke LLM
    logger.debug(f"Invoking compression LLM for tool: {tool_name}")
    response = await llm.ainvoke(messages)

    # Parse response
    content = response.content

    # Extract JSON from response (handle markdown code blocks)
    if "```json" in content:
        content = content.split("```json")[1].split("```")[0].strip()
    elif "```" in content:
        content = content.split("```")[1].split("```")[0].strip()

    # Parse JSON
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as e:
        logger.error(
            f"Failed to parse compression LLM response as JSON: {content[:500]}"
        )
        raise ValueError(f"Compression LLM returned invalid JSON: {e}")

    # Validate required fields
    required_fields = ["summary_title", "summary", "extraction", "is_useful"]
    for field in required_fields:
        if field not in parsed:
            logger.error(
                f"Compression result missing required field '{field}': {parsed}"
            )
            raise ValueError(f"Compression result missing required field: {field}")

    return parsed


def create_compression_message(
    summary_title: str,
    summary: str,
    extraction: list[str],
    artifact_file: str,
) -> AIMessage:
    """
    Create an AI message with compressed tool result for conversation injection.

    The message content contains only the compressed summary and artifact reference,
    not the raw output or plan metadata.

    Args:
        summary_title: Short title of the compressed result
        summary: Compressed summary of the tool output
        extraction: Key factual bullets extracted
        artifact_file: Filename where raw output is stored

    Returns:
        AIMessage with compressed result as JSON content
    """
    content = json.dumps(
        {
            "summary_title": summary_title,
            "summary": summary,
            "extraction": extraction,
            "artifact_file": artifact_file,
        },
        ensure_ascii=False,
    )
    return AIMessage(content=content)
