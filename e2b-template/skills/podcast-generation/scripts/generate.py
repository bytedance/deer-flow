import argparse
import base64
import json
import logging
import os
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Literal, Optional

import requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Types
class ScriptLine:
    def __init__(self, speaker: Literal["male", "female"] = "male", paragraph: str = ""):
        self.speaker = speaker
        self.paragraph = paragraph


class Script:
    def __init__(self, locale: Literal["en", "zh"] = "en", lines: Optional[list[ScriptLine]] = None):
        self.locale = locale
        self.lines = lines or []

    @classmethod
    def from_dict(cls, data: dict) -> "Script":
        script = cls(locale=data.get("locale", "en"))
        for line in data.get("lines", []):
            script.lines.append(
                ScriptLine(
                    speaker=line.get("speaker", "male"),
                    paragraph=line.get("paragraph", ""),
                )
            )
        return script


def text_to_speech(text: str, voice_type: str) -> Optional[bytes]:
    """Convert text to speech using Volcengine TTS."""
    app_id = os.getenv("VOLCENGINE_TTS_APPID")
    access_token = os.getenv("VOLCENGINE_TTS_ACCESS_TOKEN")
    cluster = os.getenv("VOLCENGINE_TTS_CLUSTER", "volcano_tts")

    if not app_id or not access_token:
        raise ValueError(
            "VOLCENGINE_TTS_APPID and VOLCENGINE_TTS_ACCESS_TOKEN environment variables must be set"
        )

    url = "https://openspeech.bytedance.com/api/v1/tts"

    # Authentication: Bearer token with semicolon separator
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer;{access_token}",
    }

    payload = {
        "app": {
            "appid": app_id,
            "token": "access_token",  # literal string, not the actual token
            "cluster": cluster,
        },
        "user": {"uid": "podcast-generator"},
        "audio": {
            "voice_type": voice_type,
            "encoding": "mp3",
            "speed_ratio": 1.2,
        },
        "request": {
            "reqid": str(uuid.uuid4()),  # must be unique UUID
            "text": text,
            "text_type": "plain",
            "operation": "query",
        },
    }

    try:
        response = requests.post(url, json=payload, headers=headers)

        if response.status_code != 200:
            logger.error(f"TTS API error: {response.status_code} - {response.text}")
            return None

        result = response.json()
        if result.get("code") != 3000:
            logger.error(f"TTS error: {result.get('message')} (code: {result.get('code')})")
            return None

        audio_data = result.get("data")
        if audio_data:
            return base64.b64decode(audio_data)

    except Exception as e:
        logger.error(f"TTS error: {str(e)}")

    return None


def _process_line(args: tuple[int, ScriptLine, int]) -> tuple[int, Optional[bytes]]:
    """Process a single script line for TTS. Returns (index, audio_bytes)."""
    i, line, total = args

    # Select voice based on speaker gender
    if line.speaker == "male":
        voice_type = "zh_male_yangguangqingnian_moon_bigtts"  # Male voice
    else:
        voice_type = "zh_female_sajiaonvyou_moon_bigtts"  # Female voice

    logger.info(f"Processing line {i + 1}/{total} ({line.speaker})")
    audio = text_to_speech(line.paragraph, voice_type)

    if not audio:
        logger.warning(f"Failed to generate audio for line {i + 1}")

    return (i, audio)


def tts_node(script: Script, max_workers: int = 4) -> list[bytes]:
    """Convert script lines to audio chunks using TTS with multi-threading."""
    logger.info(f"Converting script to audio using {max_workers} workers...")

    total = len(script.lines)
    tasks = [(i, line, total) for i, line in enumerate(script.lines)]

    # Use ThreadPoolExecutor for parallel TTS generation
    results: dict[int, Optional[bytes]] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_process_line, task): task[0] for task in tasks}
        for future in as_completed(futures):
            idx, audio = future.result()
            results[idx] = audio

    # Collect results in order, skipping failed ones
    audio_chunks = []
    for i in range(total):
        audio = results.get(i)
        if audio:
            audio_chunks.append(audio)

    logger.info(f"Generated {len(audio_chunks)} audio chunks")
    return audio_chunks


def mix_audio(audio_chunks: list[bytes]) -> bytes:
    """Combine audio chunks into a single audio file."""
    logger.info("Mixing audio chunks...")
    output = b"".join(audio_chunks)
    logger.info("Audio mixing complete")
    return output


def generate_markdown(script: Script, title: str = "Podcast Script") -> str:
    """Generate a markdown script from the podcast script."""
    lines = [f"# {title}", ""]

    for line in script.lines:
        speaker_name = "**Host (Male)**" if line.speaker == "male" else "**Host (Female)**"
        lines.append(f"{speaker_name}: {line.paragraph}")
        lines.append("")

    return "\n".join(lines)


def generate_podcast(
    script_file: str,
    output_file: str,
    transcript_file: Optional[str] = None,
) -> str:
    """Generate a podcast from a script JSON file."""

    # Read script JSON
    with open(script_file, "r", encoding="utf-8") as f:
        script_json = json.load(f)

    if "lines" not in script_json:
        raise ValueError(f"Invalid script format: missing 'lines' key. Got keys: {list(script_json.keys())}")

    script = Script.from_dict(script_json)
    logger.info(f"Loaded script with {len(script.lines)} lines")

    # Generate transcript markdown if requested
    if transcript_file:
        title = script_json.get("title", "Podcast Script")
        markdown_content = generate_markdown(script, title)
        transcript_dir = os.path.dirname(transcript_file)
        if transcript_dir:
            os.makedirs(transcript_dir, exist_ok=True)
        with open(transcript_file, "w", encoding="utf-8") as f:
            f.write(markdown_content)
        logger.info(f"Generated transcript to {transcript_file}")

    # Convert to audio
    audio_chunks = tts_node(script)

    if not audio_chunks:
        raise Exception("Failed to generate any audio")

    # Mix audio
    output_audio = mix_audio(audio_chunks)

    # Save output
    output_dir = os.path.dirname(output_file)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    with open(output_file, "wb") as f:
        f.write(output_audio)

    result = f"Successfully generated podcast to {output_file}"
    if transcript_file:
        result += f" and transcript to {transcript_file}"
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate podcast from script JSON file")
    parser.add_argument(
        "--script-file",
        required=True,
        help="Absolute path to script JSON file",
    )
    parser.add_argument(
        "--output-file",
        required=True,
        help="Output path for generated podcast MP3",
    )
    parser.add_argument(
        "--transcript-file",
        required=False,
        help="Output path for transcript markdown file (optional)",
    )

    args = parser.parse_args()

    try:
        result = generate_podcast(
            args.script_file,
            args.output_file,
            args.transcript_file,
        )
        print(result)
    except Exception as e:
        import traceback
        print(f"Error generating podcast: {e}")
        traceback.print_exc()
