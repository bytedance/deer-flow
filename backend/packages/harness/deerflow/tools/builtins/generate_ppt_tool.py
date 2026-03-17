"""Built-in tool: generate_ppt

Generates a PowerPoint presentation directly from a slide plan, bypassing
the bash sandbox entirely.  Uses sys.executable so the correct virtual-env
Python (with python-pptx installed) is always invoked, regardless of PATH.
"""

import json
import os
import subprocess
import sys
from typing import Annotated

from langchain.tools import InjectedToolCallId, ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command
from langgraph.typing import ContextT

from deerflow.agents.thread_state import ThreadState
from deerflow.sandbox.tools import (
    ensure_sandbox_initialized,
    ensure_thread_directories_exist,
    get_thread_data,
)


def _get_generate_text_script() -> str:
    """Return the absolute host path to generate_text.py."""
    from deerflow.skills.loader import get_skills_root_path

    script = get_skills_root_path() / "public" / "ppt-generation" / "scripts" / "generate_text.py"
    return str(script)


def _format_subprocess_error(result: subprocess.CompletedProcess[str]) -> str:
    """Build a concise error message from subprocess output."""
    stderr = (result.stderr or "").strip()
    stdout = (result.stdout or "").strip()
    if stderr:
        return stderr
    if stdout:
        return stdout
    return "unknown error"


@tool("generate_ppt", parse_docstring=True)
def generate_ppt_tool(
    runtime: ToolRuntime[ContextT, ThreadState],
    tool_call_id: Annotated[str, InjectedToolCallId],
    title: str,
    slides: list[dict],
    output_filename: str = "presentation.pptx",
) -> Command:
    """Generate a PowerPoint (.pptx) file from a structured slide plan.

    Use this tool instead of running bash commands to create presentations.
    The file is saved to /mnt/user-data/outputs/ and presented to the user automatically.

    Each slide dict must have:
    - "type": "title" or "content"
    - "title": slide heading
    - "subtitle": (title slides only) subtitle text
    - "key_points": (content slides only) list of bullet-point strings

    Example slides value:
    [
      {"type": "title", "title": "My Presentation", "subtitle": "A subtitle"},
      {"type": "content", "title": "Key Points", "key_points": ["Point 1", "Point 2"]}
    ]

    Args:
        title: Overall presentation title.
        slides: List of slide objects (see format above).
        output_filename: Output file name, must end with .pptx (default: presentation.pptx).
    """
    try:
        if not output_filename.endswith(".pptx"):
            output_filename += ".pptx"

        # Initialise sandbox and ensure directories exist
        ensure_sandbox_initialized(runtime)
        ensure_thread_directories_exist(runtime)
        thread_data = get_thread_data(runtime)

        if thread_data is None:
            return Command(update={"messages": [ToolMessage("Error: thread data not available", tool_call_id=tool_call_id)]})

        workspace_path = thread_data.get("workspace_path", "")
        outputs_path = thread_data.get("outputs_path", "")
        os.makedirs(workspace_path, exist_ok=True)
        os.makedirs(outputs_path, exist_ok=True)

        # Write plan JSON
        plan = {"title": title, "slides": slides}
        plan_file = os.path.join(workspace_path, "presentation-plan.json")
        with open(plan_file, "w", encoding="utf-8") as f:
            json.dump(plan, f, ensure_ascii=False, indent=2)

        output_file = os.path.join(outputs_path, output_filename)

        # Locate the script
        script_path = _get_generate_text_script()
        if not os.path.isfile(script_path):
            return Command(update={"messages": [ToolMessage(f"Error: generate_text.py not found at {script_path}", tool_call_id=tool_call_id)]})

        # Run directly with sys.executable — no shell, no PATH lookup, no encoding issues
        result = subprocess.run(
            [sys.executable, script_path, "--plan-file", plan_file, "--output-file", output_file],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )

        if result.returncode != 0:
            error = _format_subprocess_error(result)
            return Command(update={"messages": [ToolMessage(f"Error generating PPT: {error}", tool_call_id=tool_call_id)]})

        # Guard against false-success runs (script exited 0 but file missing/empty).
        if (not os.path.isfile(output_file)) or os.path.getsize(output_file) <= 0:
            diagnostic = _format_subprocess_error(result)
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            f"Error generating PPT: output file was not created at {output_file}. Details: {diagnostic}",
                            tool_call_id=tool_call_id,
                        )
                    ]
                }
            )

        virtual_pptx = f"/mnt/user-data/outputs/{output_filename}"
        return Command(
            update={
                "artifacts": [virtual_pptx],
                "messages": [ToolMessage(f"Presentation generated: {virtual_pptx}", tool_call_id=tool_call_id)],
            }
        )

    except subprocess.TimeoutExpired:
        return Command(update={"messages": [ToolMessage("Error: PPT generation timed out (60s)", tool_call_id=tool_call_id)]})
    except Exception as e:
        return Command(update={"messages": [ToolMessage(f"Error: {type(e).__name__}: {e}", tool_call_id=tool_call_id)]})
