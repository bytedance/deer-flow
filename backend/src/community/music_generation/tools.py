import logging
import os
import time

from langchain.tools import ToolRuntime, tool
from langgraph.typing import ContextT

from src.agents.thread_state import ThreadState
from src.config import get_app_config
from src.sandbox.tools import (
    ensure_sandbox_initialized,
    ensure_thread_directories_exist,
    get_thread_data,
    is_local_sandbox,
    replace_virtual_path,
)

logger = logging.getLogger(__name__)


def _get_elevenlabs_api_key() -> str | None:
    """Get the ElevenLabs API key from tool config or environment."""
    config = get_app_config().get_tool_config("generate_music")
    if config is not None:
        api_key = config.model_extra.get("api_key")
        if api_key:
            return api_key
    return os.environ.get("ELEVENLABS_API_KEY")


@tool("generate_music", parse_docstring=True)
def generate_music_tool(
    runtime: ToolRuntime[ContextT, ThreadState],
    prompt: str,
    duration_seconds: int = 30,
    instrumental: bool = False,
) -> str:
    """Generate music, songs, or audio tracks using ElevenLabs Music API. NOT for podcasts.

    Use this tool ONLY for music generation: songs, beats, instrumentals, jingles, background music, soundtracks, or any musical audio.
    Do NOT use this for podcasts or speech — use the podcast-generation skill instead for converting text into conversational podcast dialogue.
    After generation, use present_files to share the output with the user.

    Tips for good prompts:
    - Include genre, mood, tempo, and instrumentation details
    - Example: "upbeat electronic dance track with synth pads and a driving bassline, 128 BPM"
    - For instrumental tracks, set instrumental=True

    Args:
        prompt: A description of the music to generate. Include genre, mood, instruments, tempo, and style.
        duration_seconds: Duration of the track in seconds (3-300). Default 30.
        instrumental: Set to True for instrumental music with no vocals.
    """
    try:
        from elevenlabs.client import ElevenLabs

        ensure_sandbox_initialized(runtime)
        ensure_thread_directories_exist(runtime)

        api_key = _get_elevenlabs_api_key()
        if not api_key:
            return "Error: ELEVENLABS_API_KEY not configured. Please set ELEVENLABS_API_KEY in your .env file."

        duration_seconds = max(3, min(300, duration_seconds))

        logger.info(f"Generating music: prompt='{prompt[:100]}', duration={duration_seconds}s, instrumental={instrumental}")

        client = ElevenLabs(api_key=api_key)

        audio_iterator = client.music.compose(
            prompt=prompt,
            music_length_ms=duration_seconds * 1000,
            force_instrumental=instrumental,
        )

        # Generate filename and resolve paths
        sanitized = prompt[:40].replace(" ", "_").replace("/", "-").replace("'", "").replace('"', "")
        timestamp = int(time.time())
        filename = f"music_{sanitized}_{timestamp}.mp3"
        virtual_path = f"/mnt/user-data/outputs/{filename}"

        # Resolve to physical path
        physical_path = virtual_path
        if is_local_sandbox(runtime):
            thread_data = get_thread_data(runtime)
            physical_path = replace_virtual_path(virtual_path, thread_data)

        os.makedirs(os.path.dirname(physical_path), exist_ok=True)

        # Write audio chunks directly to file
        total_bytes = 0
        with open(physical_path, "wb") as f:
            for chunk in audio_iterator:
                f.write(chunk)
                total_bytes += len(chunk)

        if total_bytes == 0:
            return "Error: Music generation completed but no audio data was returned."

        size_mb = total_bytes / (1024 * 1024)
        logger.info(f"Music generated successfully: {physical_path} ({size_mb:.1f} MB)")

        return (
            f"Music generated successfully!\n"
            f"Output: {virtual_path}\n"
            f"Duration: {duration_seconds}s\n"
            f"Size: {size_mb:.1f} MB\n\n"
            f"Use present_files with [\"{virtual_path}\"] to share with the user."
        )

    except Exception as e:
        logger.error(f"Music generation failed: {e}")
        return f"Error generating music: {str(e)}"
 