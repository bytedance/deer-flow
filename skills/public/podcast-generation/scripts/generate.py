import argparse
import base64
import json
import logging
import os
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Literal, Optional

import requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Custom exception hierarchy
# ---------------------------------------------------------------------------


class PodcastGenerationError(Exception):
    """Base exception for podcast generation failures."""

    pass


class TTSError(PodcastGenerationError):
    """Raised when a single TTS call fails."""

    def __init__(
        self,
        message: str,
        line_index: Optional[int] = None,
        speaker: Optional[str] = None,
    ):
        self.line_index = line_index
        self.speaker = speaker
        super().__init__(message)


class TTSConfigurationError(TTSError):
    """Raised when TTS environment / configuration is missing or invalid."""

    pass


class TTSAPIError(TTSError):
    """Raised when the TTS API returns an HTTP-level error."""

    def __init__(
        self,
        message: str,
        status_code: int,
        response_body: str = "",
        line_index: Optional[int] = None,
        speaker: Optional[str] = None,
    ):
        self.status_code = status_code
        self.response_body = response_body
        super().__init__(message, line_index, speaker)


class TTSResponseError(TTSError):
    """Raised when the TTS API response indicates a logical/business error."""

    def __init__(
        self,
        message: str,
        error_code: Optional[int] = None,
        line_index: Optional[int] = None,
        speaker: Optional[str] = None,
    ):
        self.error_code = error_code
        super().__init__(message, line_index, speaker)


class AudioValidationError(PodcastGenerationError):
    """Raised when generated audio fails validation checks."""

    pass


class PartialPodcastError(PodcastGenerationError):
    """Raised when some (but not all) lines failed TTS conversion."""

    def __init__(
        self,
        message: str,
        total_lines: int,
        failed_lines: int,
        failed_indices: list[int],
    ):
        self.total_lines = total_lines
        self.failed_lines = failed_lines
        self.failed_indices = failed_indices
        super().__init__(message)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class ScriptLine:
    __slots__ = ("speaker", "paragraph")

    def __init__(
        self, speaker: Literal["male", "female"] = "male", paragraph: str = ""
    ):
        self.speaker = speaker
        self.paragraph = paragraph


class Script:
    __slots__ = ("locale", "lines")

    def __init__(
        self,
        locale: Literal["en", "zh"] = "en",
        lines: Optional[list[ScriptLine]] = None,
    ):
        self.locale = locale
        self.lines = lines or []

    @classmethod
    def from_dict(cls, data: dict) -> "Script":
        raw_lines = data.get("lines", [])
        script = cls(locale=data.get("locale", "en"))
        script.lines = [
            ScriptLine(
                speaker=line.get("speaker", "male"),
                paragraph=line.get("paragraph", ""),
            )
            for line in raw_lines
        ]
        return script


# ---------------------------------------------------------------------------
# TTS configuration — read once, reuse everywhere
# ---------------------------------------------------------------------------


class _TTSConfig:
    """Lazily resolved, cached TTS configuration from environment variables."""

    __slots__ = ("app_id", "access_token", "cluster", "url", "_resolved")

    _instance: Optional["_TTSConfig"] = None

    def __init__(self) -> None:
        self.app_id: Optional[str] = None
        self.access_token: Optional[str] = None
        self.cluster: str = "volcano_tts"
        self.url: str = "https://openspeech.bytedance.com/api/v1/tts"
        self._resolved: bool = False

    @classmethod
    def get(cls) -> "_TTSConfig":
        """Return the singleton config, resolving env vars on first access."""
        if cls._instance is None:
            cls._instance = cls()
        if not cls._instance._resolved:
            cls._instance._resolve()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset cached config (useful for testing)."""
        cls._instance = None

    def _resolve(self) -> None:
        self.app_id = os.getenv("VOLCENGINE_TTS_APPID")
        self.access_token = os.getenv("VOLCENGINE_TTS_ACCESS_TOKEN")
        self.cluster = os.getenv("VOLCENGINE_TTS_CLUSTER", "volcano_tts")
        self._resolved = True

    def validate(self) -> None:
        """Raise ``TTSConfigurationError`` if required values are missing."""
        if not self.app_id or not self.access_token:
            raise TTSConfigurationError(
                "VOLCENGINE_TTS_APPID and VOLCENGINE_TTS_ACCESS_TOKEN environment "
                "variables must be set. Please configure your TTS credentials."
            )


# ---------------------------------------------------------------------------
# Shared requests.Session — enables HTTP keep-alive / connection reuse
# ---------------------------------------------------------------------------

_http_session: Optional[requests.Session] = None


def _get_http_session(access_token: str) -> requests.Session:
    """Return (and lazily create) a shared ``requests.Session``."""
    global _http_session
    if _http_session is None:
        _http_session = requests.Session()
        _http_session.headers.update(
            {
                "Content-Type": "application/json",
                "Authorization": f"Bearer;{access_token}",
            }
        )
    return _http_session


# ---------------------------------------------------------------------------
# Audio validation helpers
# ---------------------------------------------------------------------------

# Minimum size in bytes for a valid MP3 audio chunk.
_MIN_AUDIO_CHUNK_SIZE = 256

# Minimum size for the final mixed podcast file (bytes).
_MIN_PODCAST_FILE_SIZE = 1024


def _validate_audio_chunk(audio_data: bytes, line_index: int) -> None:
    """Validate that an individual TTS audio chunk looks reasonable.

    Raises ``AudioValidationError`` if the audio is clearly invalid.
    """
    if not audio_data:
        raise AudioValidationError(
            f"TTS returned empty audio data for line {line_index + 1}"
        )

    if len(audio_data) < _MIN_AUDIO_CHUNK_SIZE:
        raise AudioValidationError(
            f"TTS returned suspiciously small audio ({len(audio_data)} bytes) "
            f"for line {line_index + 1}. This likely indicates a 0-second or "
            f"corrupt audio file."
        )

    # Quick MP3 frame-sync check.  Some encoders prepend an ID3 tag.
    if audio_data[:3] == b"ID3":
        return
    if len(audio_data) >= 2 and not (
        audio_data[0] == 0xFF and (audio_data[1] & 0xE0) == 0xE0
    ):
        logger.warning(
            f"Audio chunk for line {line_index + 1} does not start with a "
            f"valid MP3 frame sync (got 0x{audio_data[0]:02X}{audio_data[1]:02X}). "
            f"The audio may be corrupt."
        )


def _validate_final_audio(audio_data: bytes, total_lines: int) -> None:
    """Validate the final mixed podcast audio before writing to disk."""
    if not audio_data:
        raise AudioValidationError(
            "Final podcast audio is empty (0 bytes). All TTS conversions may "
            "have failed."
        )

    if len(audio_data) < _MIN_PODCAST_FILE_SIZE:
        raise AudioValidationError(
            f"Final podcast audio is only {len(audio_data)} bytes — this almost "
            f"certainly represents a 0-second or corrupt audio file. "
            f"Expected a substantially larger file for {total_lines} script lines."
        )


# ---------------------------------------------------------------------------
# TTS conversion
# ---------------------------------------------------------------------------


def text_to_speech(
    text: str,
    voice_type: str,
    config: "_TTSConfig",
    session: requests.Session,
    line_index: int = 0,
) -> bytes:
    """Convert text to speech using Volcengine TTS.

    Callers must supply a pre-validated ``_TTSConfig`` and a shared
    ``requests.Session`` to avoid redundant env-var lookups and TCP
    connection overhead.

    Returns the raw MP3 bytes on success.
    """
    if not text or not text.strip():
        raise TTSError(
            f"Cannot convert empty text to speech (line {line_index + 1}).",
            line_index=line_index,
        )

    payload = {
        "app": {
            "appid": config.app_id,
            "token": "access_token",
            "cluster": config.cluster,
        },
        "user": {"uid": "podcast-generator"},
        "audio": {
            "voice_type": voice_type,
            "encoding": "mp3",
            "speed_ratio": 1.2,
        },
        "request": {
            "reqid": str(uuid.uuid4()),
            "text": text,
            "text_type": "plain",
            "operation": "query",
        },
    }

    try:
        response = session.post(config.url, json=payload, timeout=60)
    except requests.exceptions.Timeout as exc:
        raise TTSAPIError(
            f"TTS API request timed out for line {line_index + 1}: {exc}",
            status_code=0,
            line_index=line_index,
        ) from exc
    except requests.exceptions.ConnectionError as exc:
        raise TTSAPIError(
            f"Failed to connect to TTS API for line {line_index + 1}: {exc}",
            status_code=0,
            line_index=line_index,
        ) from exc
    except requests.exceptions.RequestException as exc:
        raise TTSAPIError(
            f"TTS API request failed for line {line_index + 1}: {exc}",
            status_code=0,
            line_index=line_index,
        ) from exc

    if response.status_code != 200:
        raise TTSAPIError(
            f"TTS API returned HTTP {response.status_code} for line "
            f"{line_index + 1}: {response.text[:500]}",
            status_code=response.status_code,
            response_body=response.text[:2000],
            line_index=line_index,
        )

    try:
        result = response.json()
    except (json.JSONDecodeError, ValueError) as exc:
        raise TTSResponseError(
            f"TTS API returned invalid JSON for line {line_index + 1}: "
            f"{response.text[:500]}",
            line_index=line_index,
        ) from exc

    api_code = result.get("code")
    if api_code != 3000:
        raise TTSResponseError(
            f"TTS API error for line {line_index + 1}: "
            f"{result.get('message', 'unknown error')} (code: {api_code})",
            error_code=api_code,
            line_index=line_index,
        )

    audio_data_b64 = result.get("data")
    if not audio_data_b64:
        raise TTSResponseError(
            f"TTS API returned success code but no audio data for line "
            f"{line_index + 1}.",
            error_code=api_code,
            line_index=line_index,
        )

    try:
        audio_bytes = base64.b64decode(audio_data_b64)
    except Exception as exc:
        raise TTSResponseError(
            f"Failed to decode base64 audio data for line {line_index + 1}: {exc}",
            line_index=line_index,
        ) from exc

    _validate_audio_chunk(audio_bytes, line_index)
    return audio_bytes


# ---------------------------------------------------------------------------
# Line processing (used by thread pool)
# ---------------------------------------------------------------------------


def _process_line(
    args: tuple[int, ScriptLine, int],
    config: "_TTSConfig",
    session: requests.Session,
) -> tuple[int, bytes]:
    """Process a single script line for TTS. Returns (index, audio_bytes)."""
    i, line, total = args

    voice_type = (
        "zh_male_yangguangqingnian_moon_bigtts"
        if line.speaker == "male"
        else "zh_female_sajiaonvyou_moon_bigtts"
    )

    logger.info(f"Processing line {i + 1}/{total} ({line.speaker})")
    audio = text_to_speech(line.paragraph, voice_type, config, session, line_index=i)
    logger.info(
        f"Successfully generated audio for line {i + 1}/{total} ({len(audio)} bytes)"
    )
    return (i, audio)


# ---------------------------------------------------------------------------
# TTS orchestration
# ---------------------------------------------------------------------------


def tts_node(
    script: Script, max_workers: int = 4, fail_fast: bool = True
) -> list[bytes]:
    """Convert script lines to audio chunks using TTS with multi-threading.

    Parameters
    ----------
    script : Script
        The podcast script to convert.
    max_workers : int
        Number of parallel TTS workers.
    fail_fast : bool
        If ``True`` (default), raise immediately when *any* line fails.
        If ``False``, collect all results and raise ``PartialPodcastError``
        only if at least one line failed.

    Returns
    -------
    list[bytes]
        Ordered list of audio chunks (one per script line).
    """
    if not script.lines:
        raise PodcastGenerationError(
            "Cannot generate podcast: script contains no lines."
        )

    # Validate config once before spawning threads
    config = _TTSConfig.get()
    config.validate()

    session = _get_http_session(config.access_token)  # type: ignore[arg-type]

    total = len(script.lines)
    logger.info(
        f"Converting {total} script lines to audio using {max_workers} workers..."
    )

    tasks = [(i, line, total) for i, line in enumerate(script.lines)]

    results: dict[int, bytes] = {}
    errors: dict[int, Exception] = {}

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_process_line, task, config, session): task[0]
            for task in tasks
        }
        for future in as_completed(futures):
            idx = futures[future]
            try:
                returned_idx, audio = future.result()
                results[returned_idx] = audio
            except Exception as exc:
                errors[idx] = exc
                logger.error(f"TTS failed for line {idx + 1}: {exc}")
                if fail_fast:
                    for f in futures:
                        f.cancel()
                    raise PodcastGenerationError(
                        f"TTS processing failed for line {idx + 1}/{total}. "
                        f"Aborting podcast generation. Error: {exc}"
                    ) from exc

    # Handle partial failures (only reachable when fail_fast is False)
    if errors:
        failed_indices = sorted(errors.keys())
        error_summary = "\n".join(
            f"  - Line {fi + 1}: {errors[fi]}" for fi in failed_indices
        )
        raise PartialPodcastError(
            f"TTS failed for {len(errors)} out of {total} lines:\n"
            f"{error_summary}\n"
            f"No audio file was generated to avoid producing an incomplete "
            f"or 0-second podcast.",
            total_lines=total,
            failed_lines=len(errors),
            failed_indices=failed_indices,
        )

    # Collect results in order
    audio_chunks: list[bytes] = []
    for i in range(total):
        audio = results.get(i)
        if audio is None:
            raise PodcastGenerationError(
                f"Internal error: no audio data and no error recorded for "
                f"line {i + 1}. This is a bug."
            )
        audio_chunks.append(audio)

    logger.info(f"Successfully generated {len(audio_chunks)}/{total} audio chunks")
    return audio_chunks


# ---------------------------------------------------------------------------
# Audio mixing
# ---------------------------------------------------------------------------


def mix_audio(audio_chunks: list[bytes]) -> bytes:
    """Combine audio chunks into a single audio file."""
    if not audio_chunks:
        raise AudioValidationError(
            "Cannot mix audio: received 0 audio chunks. "
            "All TTS conversions appear to have failed."
        )

    logger.info(f"Mixing {len(audio_chunks)} audio chunks...")
    output = b"".join(audio_chunks)
    logger.info(f"Audio mixing complete — total size: {len(output)} bytes")
    return output


# ---------------------------------------------------------------------------
# Markdown transcript generation
# ---------------------------------------------------------------------------


def generate_markdown(script: Script, title: str = "Podcast Script") -> str:
    """Generate a markdown script from the podcast script."""
    parts = [f"# {title}", ""]
    for line in script.lines:
        speaker_name = (
            "**Host (Male)**" if line.speaker == "male" else "**Host (Female)**"
        )
        parts.append(f"{speaker_name}: {line.paragraph}")
        parts.append("")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


def generate_podcast(
    script_file: str,
    output_file: str,
    transcript_file: Optional[str] = None,
) -> str:
    """Generate a podcast from a script JSON file.

    Raises
    ------
    FileNotFoundError
        If the script file does not exist.
    ValueError
        If the script JSON is malformed.
    PodcastGenerationError
        If TTS processing or audio validation fails.
    """

    # ------------------------------------------------------------------
    # 1. Read & validate input
    # ------------------------------------------------------------------
    if not os.path.isfile(script_file):
        raise FileNotFoundError(f"Script file not found: {script_file}")

    try:
        with open(script_file, "r", encoding="utf-8") as f:
            script_json = json.load(f)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Script file contains invalid JSON: {script_file}. Error: {exc}"
        ) from exc

    if "lines" not in script_json:
        raise ValueError(
            f"Invalid script format: missing 'lines' key. "
            f"Got keys: {list(script_json.keys())}"
        )

    if not script_json["lines"]:
        raise ValueError(
            "Invalid script format: 'lines' array is empty. "
            "At least one line is required."
        )

    script = Script.from_dict(script_json)
    logger.info(f"Loaded script with {len(script.lines)} lines")

    # Validate that every line has non-empty text
    for idx, line in enumerate(script.lines):
        if not line.paragraph or not line.paragraph.strip():
            raise ValueError(
                f"Script line {idx + 1} has empty paragraph text. "
                f"Every line must contain speech content."
            )

    # ------------------------------------------------------------------
    # 2. Generate transcript markdown (if requested)
    # ------------------------------------------------------------------
    if transcript_file:
        title = script_json.get("title", "Podcast Script")
        markdown_content = generate_markdown(script, title)
        transcript_dir = os.path.dirname(transcript_file)
        if transcript_dir:
            os.makedirs(transcript_dir, exist_ok=True)
        with open(transcript_file, "w", encoding="utf-8") as f:
            f.write(markdown_content)
        logger.info(f"Generated transcript to {transcript_file}")

    # ------------------------------------------------------------------
    # 3. Convert to audio via TTS
    # ------------------------------------------------------------------
    audio_chunks = tts_node(script)

    # ------------------------------------------------------------------
    # 4. Mix audio
    # ------------------------------------------------------------------
    output_audio = mix_audio(audio_chunks)

    # ------------------------------------------------------------------
    # 5. Validate final audio before writing
    # ------------------------------------------------------------------
    _validate_final_audio(output_audio, total_lines=len(script.lines))

    # ------------------------------------------------------------------
    # 6. Save output
    # ------------------------------------------------------------------
    output_dir = os.path.dirname(output_file)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    with open(output_file, "wb") as f:
        f.write(output_audio)

    actual_size = os.path.getsize(output_file)
    if actual_size == 0:
        raise AudioValidationError(
            f"Output file {output_file} is 0 bytes after writing. "
            f"The podcast audio was not saved correctly."
        )

    logger.info(
        f"Podcast saved to {output_file} ({actual_size} bytes, "
        f"{len(audio_chunks)} segments)"
    )

    result = f"Successfully generated podcast to {output_file} ({actual_size} bytes)"
    if transcript_file:
        result += f" and transcript to {transcript_file}"
    return result


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate podcast from script JSON file"
    )
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
    except TTSConfigurationError as e:
        print(f"[CONFIGURATION ERROR] {e}", file=sys.stderr)
        sys.exit(2)
    except TTSAPIError as e:
        print(f"[TTS API ERROR] {e}", file=sys.stderr)
        sys.exit(3)
    except TTSResponseError as e:
        print(f"[TTS RESPONSE ERROR] {e}", file=sys.stderr)
        sys.exit(3)
    except PartialPodcastError as e:
        print(
            f"[PARTIAL FAILURE] {e.failed_lines}/{e.total_lines} lines failed. "
            f"Failed lines: {[i + 1 for i in e.failed_indices]}",
            file=sys.stderr,
        )
        print(f"[PARTIAL FAILURE] {e}", file=sys.stderr)
        sys.exit(4)
    except AudioValidationError as e:
        print(f"[AUDIO VALIDATION ERROR] {e}", file=sys.stderr)
        sys.exit(5)
    except PodcastGenerationError as e:
        print(f"[PODCAST GENERATION ERROR] {e}", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError as e:
        print(f"[FILE NOT FOUND] {e}", file=sys.stderr)
        sys.exit(6)
    except ValueError as e:
        print(f"[INVALID INPUT] {e}", file=sys.stderr)
        sys.exit(7)
    except Exception as e:
        import traceback

        print(f"[UNEXPECTED ERROR] Error generating podcast: {e}", file=sys.stderr)
        traceback.print_exc()
        sys.exit(99)
