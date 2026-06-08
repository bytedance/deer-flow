import argparse
import base64
import json
import logging
import os
import random
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Literal, Optional

import requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MINIMAX_DEFAULT_HOST = "https://api.minimaxi.com"
# MiniMax base_resp codes worth retrying: unknown, timeout, RPM limit, TPM limit.
MINIMAX_RETRYABLE_CODES = {1000, 1001, 1002, 1039}
DEFAULT_TTS_MAX_RETRIES = 4
DEFAULT_MAX_WORKERS = 4
DEFAULT_MINIMAX_MAX_WORKERS = 1


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
                ScriptLine(speaker=line.get("speaker", "male"),
                           paragraph=line.get("paragraph", ""))
            )
        return script


def _resolve_provider(override_env: str, existing_provider: str, has_existing_creds: bool) -> str:
    override = os.getenv(override_env)
    if override:
        return override.strip().lower()
    if has_existing_creds:
        return existing_provider
    if os.getenv("MINIMAX_API_KEY"):
        return "minimax"
    raise ValueError(
        f"No credentials found. Set VOLCENGINE_TTS_APPID + VOLCENGINE_TTS_ACCESS_TOKEN "
        f"for {existing_provider}, or MINIMAX_API_KEY for minimax "
        f"(optionally force with {override_env})."
    )


def _resolve_tts_provider() -> str:
    has_volc = bool(
        os.getenv("VOLCENGINE_TTS_APPID") and os.getenv("VOLCENGINE_TTS_ACCESS_TOKEN")
    )
    provider = _resolve_provider("PODCAST_GENERATION_PROVIDER", "volcengine", has_volc)
    if provider not in ("volcengine", "minimax"):
        raise ValueError(
            f"Unknown podcast provider: {provider!r} (use 'volcengine' or 'minimax')"
        )
    return provider


def _default_max_retries() -> int:
    try:
        return int(os.getenv("MINIMAX_TTS_MAX_RETRIES", str(DEFAULT_TTS_MAX_RETRIES)))
    except ValueError:
        return DEFAULT_TTS_MAX_RETRIES


def _default_max_workers(provider: str) -> int:
    """Each provider owns its own concurrency: MiniMax stays low to avoid rate
    limits, Volcengine keeps the historical default. Not user-tunable by design.
    """
    if provider == "minimax":
        return DEFAULT_MINIMAX_MAX_WORKERS
    return DEFAULT_MAX_WORKERS


def _parse_retry_after(response) -> Optional[float]:
    """Return the server-provided Retry-After (seconds), if any."""
    headers = getattr(response, "headers", None) or {}
    value = headers.get("Retry-After")
    try:
        return float(value) if value else None
    except (TypeError, ValueError):
        return None


def _backoff_sleep(attempt: int, retry_after: Optional[float]) -> None:
    """Sleep with exponential backoff + jitter, honoring Retry-After when present.

    Jitter de-synchronizes concurrent workers that all got rate-limited at once,
    avoiding a thundering-herd retry storm.
    """
    base = retry_after if retry_after else min(2 ** attempt, 30)
    time.sleep(base + random.uniform(0, 1))


def text_to_speech_volcengine(
    text: str, voice_type: str, max_retries: Optional[int] = None
) -> Optional[bytes]:
    """Convert text to speech using Volcengine TTS (returns base64-decoded mp3 bytes).

    Retries with exponential backoff on transient HTTP errors (429 / 5xx).
    """
    app_id = os.getenv("VOLCENGINE_TTS_APPID")
    access_token = os.getenv("VOLCENGINE_TTS_ACCESS_TOKEN")
    cluster = os.getenv("VOLCENGINE_TTS_CLUSTER", "volcano_tts")
    if max_retries is None:
        max_retries = _default_max_retries()
    url = "https://openspeech.bytedance.com/api/v1/tts"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer;{access_token}"}
    payload = {
        "app": {"appid": app_id, "token": "access_token", "cluster": cluster},
        "user": {"uid": "podcast-generator"},
        "audio": {"voice_type": voice_type, "encoding": "mp3", "speed_ratio": 1.2},
        "request": {"reqid": str(uuid.uuid4()), "text": text,
                    "text_type": "plain", "operation": "query"},
    }
    for attempt in range(max_retries + 1):
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=60)
        except Exception as e:
            logger.error(f"TTS error: {e}")
            if attempt < max_retries:
                _backoff_sleep(attempt, None)
                continue
            return None
        if response.status_code == 429 or response.status_code >= 500:
            logger.warning(
                f"Volcengine TTS transient HTTP {response.status_code} "
                f"(attempt {attempt + 1}/{max_retries + 1})"
            )
            if attempt < max_retries:
                _backoff_sleep(attempt, _parse_retry_after(response))
                continue
            return None
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
        return None
    return None


def text_to_speech_minimax(
    text: str, voice_id: str, max_retries: Optional[int] = None
) -> Optional[bytes]:
    """Convert text to speech using MiniMax t2a_v2 (returns hex-decoded mp3 bytes).

    Retries with exponential backoff on HTTP 429/5xx and on retryable base_resp
    codes (rate/TPM limits, timeouts). Permanent errors (auth, balance, bad input)
    are not retried.
    """
    api_key = os.getenv("MINIMAX_API_KEY")
    host = os.getenv("MINIMAX_API_HOST", MINIMAX_DEFAULT_HOST).rstrip("/")
    if max_retries is None:
        max_retries = _default_max_retries()
    payload = {
        "model": os.getenv("MINIMAX_TTS_MODEL", "speech-2.6-hd"),
        "text": text,
        "voice_setting": {"voice_id": voice_id, "speed": 1.0, "vol": 1.0, "pitch": 0},
        "audio_setting": {"sample_rate": 32000, "bitrate": 128000, "format": "mp3", "channel": 1},
        "output_format": "hex",
    }
    for attempt in range(max_retries + 1):
        try:
            response = requests.post(
                f"{host}/v1/t2a_v2",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=60,
            )
        except Exception as e:
            logger.error(f"MiniMax TTS error: {e}")
            if attempt < max_retries:
                _backoff_sleep(attempt, None)
                continue
            return None
        if response.status_code == 429 or response.status_code >= 500:
            logger.warning(
                f"MiniMax TTS rate-limited HTTP {response.status_code} "
                f"(attempt {attempt + 1}/{max_retries + 1})"
            )
            if attempt < max_retries:
                _backoff_sleep(attempt, _parse_retry_after(response))
                continue
            return None
        if response.status_code != 200:
            logger.error(f"MiniMax TTS error: {response.status_code} - {response.text}")
            return None
        result = response.json()
        base = result.get("base_resp") or {}
        code = base.get("status_code", 0)
        if code in MINIMAX_RETRYABLE_CODES:
            logger.warning(
                f"MiniMax TTS retryable error {code}: {base.get('status_msg')} "
                f"(attempt {attempt + 1}/{max_retries + 1})"
            )
            if attempt < max_retries:
                _backoff_sleep(attempt, None)
                continue
            return None
        if code != 0:
            logger.error(f"MiniMax TTS error {code}: {base.get('status_msg')}")
            return None
        audio_hex = (result.get("data") or {}).get("audio")
        if audio_hex:
            return bytes.fromhex(audio_hex)
        return None
    return None


def _process_line(args: tuple[int, ScriptLine, int, str]) -> tuple[int, Optional[bytes]]:
    """Process a single script line for TTS. Returns (index, audio_bytes)."""
    i, line, total, provider = args
    logger.info(f"Processing line {i + 1}/{total} ({line.speaker}) via {provider}")
    if provider == "minimax":
        if line.speaker == "male":
            voice = os.getenv("MINIMAX_TTS_VOICE_MALE", "male-qn-qingse")
        else:
            voice = os.getenv("MINIMAX_TTS_VOICE_FEMALE", "female-tianmei")
        audio = text_to_speech_minimax(line.paragraph, voice)
    else:
        if line.speaker == "male":
            voice = "zh_male_yangguangqingnian_moon_bigtts"
        else:
            voice = "zh_female_sajiaonvyou_moon_bigtts"
        audio = text_to_speech_volcengine(line.paragraph, voice)
    if not audio:
        logger.warning(f"Failed to generate audio for line {i + 1}")
    return (i, audio)


def tts_node(script: Script) -> list[bytes]:
    """Convert script lines to audio chunks using TTS with multi-threading.

    Concurrency is owned by the resolved provider (see _default_max_workers);
    there is no caller-facing knob. Fails loudly: if any line cannot be
    synthesized (even after retries), raise rather than silently emitting an
    incomplete podcast.
    """
    total = len(script.lines)
    if total == 0:
        raise ValueError("Script contains no lines to process")

    provider = _resolve_tts_provider()
    max_workers = _default_max_workers(provider)
    if provider == "volcengine" and not (
        os.getenv("VOLCENGINE_TTS_APPID") and os.getenv("VOLCENGINE_TTS_ACCESS_TOKEN")
    ):
        raise ValueError(
            "Volcengine TTS selected but VOLCENGINE_TTS_APPID / "
            "VOLCENGINE_TTS_ACCESS_TOKEN are not set"
        )
    if provider == "minimax" and not os.getenv("MINIMAX_API_KEY"):
        raise ValueError("MiniMax TTS selected but MINIMAX_API_KEY is not set")
    logger.info(f"Converting script to audio using {max_workers} workers (provider={provider})...")
    tasks = [(i, line, total, provider) for i, line in enumerate(script.lines)]

    results: dict[int, Optional[bytes]] = {}
    failed_indices: list[int] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_process_line, task): task[0] for task in tasks}
        for future in as_completed(futures):
            idx, audio = future.result()
            results[idx] = audio
            if not audio:
                failed_indices.append(idx)

    if failed_indices:
        raise ValueError(
            f"TTS failed for {len(failed_indices)}/{total} lines after retries: "
            f"line numbers {sorted(i + 1 for i in failed_indices)}. "
            f"This is usually transient API rate limiting — wait a moment and retry."
        )

    audio_chunks = [results[i] for i in range(total)]
    logger.info(f"Generated {len(audio_chunks)}/{total} audio chunks successfully")
    return audio_chunks


def mix_audio(audio_chunks: list[bytes]) -> bytes:
    """Combine audio chunks into a single audio file."""
    if not audio_chunks:
        raise ValueError("No audio chunks to mix - TTS generation may have failed")
    output = b"".join(audio_chunks)
    if len(output) == 0:
        raise ValueError("Mixed audio is empty - TTS generation may have failed")
    logger.info(f"Audio mixing complete: {len(output)} bytes")
    return output


def generate_markdown(script: Script, title: str = "Podcast Script") -> str:
    lines = [f"# {title}", ""]
    for line in script.lines:
        speaker_name = "**Host (Male)**" if line.speaker == "male" else "**Host (Female)**"
        lines.append(f"{speaker_name}: {line.paragraph}")
        lines.append("")
    return "\n".join(lines)


def generate_podcast(script_file: str, output_file: str,
                     transcript_file: Optional[str] = None) -> str:
    with open(script_file, "r", encoding="utf-8") as f:
        script_json = json.load(f)
    if "lines" not in script_json:
        raise ValueError(
            f"Invalid script format: missing 'lines' key. Got keys: {list(script_json.keys())}"
        )
    script = Script.from_dict(script_json)
    logger.info(f"Loaded script with {len(script.lines)} lines")

    if transcript_file:
        title = script_json.get("title", "Podcast Script")
        markdown_content = generate_markdown(script, title)
        transcript_dir = os.path.dirname(transcript_file)
        if transcript_dir:
            os.makedirs(transcript_dir, exist_ok=True)
        with open(transcript_file, "w", encoding="utf-8") as f:
            f.write(markdown_content)
        logger.info(f"Generated transcript to {transcript_file}")

    audio_chunks = tts_node(script)
    if not audio_chunks:
        raise Exception("Failed to generate any audio")
    output_audio = mix_audio(audio_chunks)

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
    parser.add_argument("--script-file", required=True, help="Absolute path to script JSON file")
    parser.add_argument("--output-file", required=True, help="Output path for generated podcast MP3")
    parser.add_argument("--transcript-file", required=False,
                        help="Output path for transcript markdown file (optional)")
    args = parser.parse_args()

    try:
        result = generate_podcast(args.script_file, args.output_file,
                                  args.transcript_file)
        print(result)
    except Exception as e:
        import traceback
        print(f"Error generating podcast: {e}")
        traceback.print_exc()
