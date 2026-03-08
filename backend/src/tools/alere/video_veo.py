"""Google Veo Video Generation tool for Alere's Node 1 (Activation)."""

import os
import subprocess
from typing import List, Optional
from langchain.tools import tool

@tool("video_veo_tool", parse_docstring=True)
def video_veo_tool(
    prompt_json: str,
    output_path: str,
    reference_images: Optional[List[str]] = None
) -> str:
    """Generates an activation video using Google Veo for Alere Learning Situations.
    This video is intended to trigger 'Cognitive Imbalance' (Node 1).

    Args:
        prompt_json: A detailed JSON string describing the scene, mood, and educational trigger.
        output_path: The absolute path where the generated video should be saved.
        reference_images: A list of absolute paths to images to guide the generation (optional).
    """
    # In a real environment, this would call the Google Veo API.
    # We'll adapt the existing video-generation script if available or simulate the call.

    script_path = "/mnt/skills/public/video-generation/scripts/generate.py"

    # Save the prompt_json to a temporary file for the script
    workspace_path = "/mnt/user-data/workspace/"
    if not os.path.exists(workspace_path):
        os.makedirs(workspace_path, exist_ok=True)

    prompt_file = os.path.join(workspace_path, "veo_activation_prompt.json")
    with open(prompt_file, "w") as f:
        f.write(prompt_json)

    cmd = [
        "python", script_path,
        "--prompt-file", prompt_file,
        "--output-file", output_path,
        "--aspect-ratio", "16:9"
    ]

    if reference_images:
        cmd.extend(["--reference-images"] + reference_images)

    try:
        # Check if the script exists
        if not os.path.exists(script_path):
             return f"Error: video-generation skill not found at {script_path}. Please ensure it is installed."

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            return f"Activation Video generated successfully at {output_path} using Google Veo logic."
        else:
            return f"Error generating video: {result.stderr}"
    except Exception as e:
        return f"Unexpected error during video generation: {str(e)}"
