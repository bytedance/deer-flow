#!/usr/bin/env python3
"""Deterministic preflight validator for beat-synced commercial video prompts."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REQUIRED_SECTIONS = (
    "CHARACTER DIRECTION",
    "REFERENCE MAP",
    "ENVIRONMENT",
    "AUDIO DIRECTION",
    "SHOT LIST",
    "CONTINUITY AND PRODUCT CONSISTENCY",
)

BANNED_EN_TERMS = (
    "epic",
    "beautiful",
    "stunning",
    "amazing",
    "masterpiece",
    "8k",
    "ultra-realistic",
    "award-winning",
    "emotional",
    "happy expression",
)

BANNED_ZH_TERMS = (
    "唯美",
    "震撼",
    "史诗感",
    "超高清",
    "氛围感拉满",
)

BANNED_CAMERA_BRANDS = (
    "arri",
    "alexa",
    "sony fx",
    "canon c300",
    "red komodo",
    "red v-raptor",
)

BANNED_NEGATIVE_MUSIC_TERMS = (
    "no music",
    "ambient only",
    "music fades to silence",
)

_SHOT_LINE_RE = re.compile(r"^(\d+)s-(\d+)s\s*\(([^)]+)\):\s*(.+)$")
_IMAGE_REF_RE = re.compile(r"@Image\s+(\d+)")
_CAPTION_RE = re.compile(r"【([^】]+)】")
_BRACE_RE = re.compile(r"\{([^}]+)\}")
_SPEECH_LINE_RE = re.compile(
    r"(?:Voiceover|On-camera dialogue\s*\(lip-synced\)):\s*([^\n(<【}]+)",
    re.IGNORECASE,
)
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_WORD_RE = re.compile(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*")
_EMOJI_RE = re.compile(
    "["
    "\U0001f300-\U0001faff"
    "\U00002600-\U000027bf"
    "\U0001f1e0-\U0001f1ff"
    "\U0000fe0f"
    "]+"
)

MAX_CAPTIONS = 3
MAX_CAPTION_EN_WORDS = 6
MAX_CAPTION_ZH_CHARS = 10
MAX_SPEECH_EN_WORDS = 18
MAX_SPEECH_ZH_CHARS = 35


@dataclass(frozen=True)
class PreflightResult:
    """Structured preflight outcome."""

    ok: bool
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    shot_count: int
    caption_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "shot_count": self.shot_count,
            "caption_count": self.caption_count,
        }


def _parse_sections(text: str, errors: list[str]) -> dict[str, list[str]]:
    """Split prompt text into top-level sections by exact header line."""
    sections: dict[str, list[str]] = {}
    current: str | None = None
    header_set = set(REQUIRED_SECTIONS)
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if stripped in header_set:
            if stripped in sections:
                errors.append(f"Duplicate section header: {stripped}")
            else:
                sections[stripped] = []
            current = stripped
            continue
        if current is not None:
            sections[current].append(raw_line)
    return sections


def _check_banned_terms(text: str, errors: list[str]) -> None:
    """Flag banned adjectives, camera brands, negative music cues, and emoji."""
    for term in BANNED_EN_TERMS + BANNED_CAMERA_BRANDS + BANNED_NEGATIVE_MUSIC_TERMS:
        pattern = re.compile(r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])", re.IGNORECASE)
        if pattern.search(text):
            errors.append(f"Banned term detected: {term!r}")

    for term in BANNED_ZH_TERMS:
        if term in text:
            errors.append(f"Banned term detected: {term!r}")

    emoji_match = _EMOJI_RE.search(text)
    if emoji_match:
        errors.append(f"Emoji or decorative symbol is not allowed: {emoji_match.group(0)!r}")


def _check_captions(text: str, errors: list[str]) -> int:
    """Validate caption count and per-caption word/character budget."""
    captions = _CAPTION_RE.findall(text)
    if len(captions) > MAX_CAPTIONS:
        errors.append(f"Too many captions: found {len(captions)}, maximum is {MAX_CAPTIONS}")

    for idx, caption in enumerate(captions, start=1):
        cjk_count = len(_CJK_RE.findall(caption))
        word_count = len(_WORD_RE.findall(caption))
        if cjk_count > 0:
            if cjk_count + word_count > MAX_CAPTION_ZH_CHARS:
                errors.append(f"Caption #{idx} ({caption!r}) exceeds Chinese budget of {MAX_CAPTION_ZH_CHARS} characters")
        elif word_count > MAX_CAPTION_EN_WORDS:
            errors.append(f"Caption #{idx} ({caption!r}) exceeds English budget of {MAX_CAPTION_EN_WORDS} words ({word_count})")
    return len(captions)


def _check_speech(text: str, audio_text: str, errors: list[str]) -> None:
    """Validate SPEECH INVENTORY declaration and optional voiceover budget."""
    if "SPEECH INVENTORY:" not in audio_text:
        errors.append("AUDIO DIRECTION must declare 'SPEECH INVENTORY:'")

    zero_speech = bool(
        re.search(
            r"SPEECH INVENTORY:\s*0\s+on-camera[^.\n]*\band\s+0\s+voiceover",
            audio_text,
            re.IGNORECASE,
        )
    )
    braces = _BRACE_RE.findall(text)
    if zero_speech and braces:
        errors.append("Curly braces '{...}' must be omitted when SPEECH INVENTORY declares 0 speech lines")

    speech_segments = _SPEECH_LINE_RE.findall(text)
    if not speech_segments and not zero_speech and braces:
        speech_segments = braces

    if speech_segments:
        combined = " ".join(speech_segments)
        cjk_count = len(_CJK_RE.findall(combined))
        word_count = len(_WORD_RE.findall(combined))
        if cjk_count > 0:
            if cjk_count + word_count > MAX_SPEECH_ZH_CHARS:
                errors.append(f"Spoken lines exceed Chinese budget of {MAX_SPEECH_ZH_CHARS} characters")
        elif word_count > MAX_SPEECH_EN_WORDS:
            errors.append(f"Spoken lines exceed English budget of {MAX_SPEECH_EN_WORDS} words ({word_count})")


def _check_shots(
    shot_lines: list[str],
    expected_duration: int,
    errors: list[str],
    warnings: list[str],
) -> int:
    """Validate shot formatting, contiguous timecodes, and per-shot music cues."""
    non_empty = [line.strip() for line in shot_lines if line.strip()]
    if not non_empty:
        errors.append("SHOT LIST has no shot lines")
        return 0

    prev_end = 0
    parsed_count = 0
    for idx, line in enumerate(non_empty, start=1):
        if line.startswith(("-", "*", "•", "{", "[")):
            errors.append(f"SHOT LIST line {idx} must be plain text, not Markdown list or JSON: {line[:60]!r}")
            continue

        match = _SHOT_LINE_RE.match(line)
        if not match:
            errors.append(f"SHOT LIST line {idx} does not match 'Ns-Ms (shot K, ...): ...': {line[:60]!r}")
            continue

        start_s = int(match.group(1))
        end_s = int(match.group(2))
        body = match.group(4)
        parsed_count += 1

        if end_s <= start_s:
            errors.append(f"Shot {idx} has non-positive duration ({start_s}s-{end_s}s)")
        if start_s != prev_end:
            errors.append(f"Shot {idx} timecode gap/overlap: expected start {prev_end}s, got {start_s}s")
        prev_end = end_s

        if not re.search(r"\([^)]+\)", body):
            errors.append(f"Shot {idx} ({start_s}s-{end_s}s) is missing a '(music cue)' marker")

    if parsed_count > 0 and expected_duration > 0 and prev_end != expected_duration:
        errors.append(f"SHOT LIST ends at {prev_end}s, expected {expected_duration}s")

    if parsed_count > 0 and expected_duration == 15 and not (6 <= parsed_count <= 8):
        warnings.append(f"15s commercial default recommends 6-8 shots; found {parsed_count}")

    return parsed_count


def _check_image_references(
    ref_map_text: str,
    shot_list_text: str,
    image_count: int,
    errors: list[str],
) -> None:
    """Verify every supplied image is declared in REFERENCE MAP and used in SHOT LIST."""
    if image_count <= 0:
        return

    declared = {int(n) for n in _IMAGE_REF_RE.findall(ref_map_text)}
    used = {int(n) for n in _IMAGE_REF_RE.findall(shot_list_text)}
    expected = set(range(1, image_count + 1))

    missing_decl = sorted(expected - declared)
    if missing_decl:
        refs = ", ".join(f"@Image {n}" for n in missing_decl)
        errors.append(f"REFERENCE MAP is missing declaration(s): {refs}")

    missing_used = sorted(expected - used)
    if missing_used:
        refs = ", ".join(f"@Image {n}" for n in missing_used)
        errors.append(f"SHOT LIST must reference every image at least once; missing: {refs}")

    out_of_range = sorted(n for n in (declared | used) if n < 1 or n > image_count)
    if out_of_range:
        refs = ", ".join(f"@Image {n}" for n in out_of_range)
        errors.append(f"Out-of-range image reference(s) for image_count={image_count}: {refs}")


def validate_prompt(
    text: str,
    *,
    image_count: int = 0,
    expected_duration: int = 15,
) -> PreflightResult:
    """Run all deterministic preflight checks against a commercial video prompt."""
    if image_count < 0:
        raise ValueError(f"image_count must be >= 0, got {image_count}")
    if expected_duration != -1 and expected_duration <= 0:
        raise ValueError(f"expected_duration must be a positive integer or -1, got {expected_duration}")

    errors: list[str] = []
    warnings: list[str] = []

    stripped = text.strip()
    if not stripped:
        return PreflightResult(
            ok=False,
            errors=("Prompt file is empty",),
            warnings=(),
            shot_count=0,
            caption_count=0,
        )

    if stripped.startswith("{") or stripped.startswith("["):
        errors.append("Prompt must be plain text, not JSON")

    sections = _parse_sections(text, errors)
    for header in REQUIRED_SECTIONS:
        if header not in sections:
            errors.append(f"Missing required section: {header}")
        elif not any(line.strip() for line in sections[header]):
            errors.append(f"Section {header} is empty")

    _check_banned_terms(text, errors)
    caption_count = _check_captions(text, errors)

    audio_text = "\n".join(sections.get("AUDIO DIRECTION", ()))
    if "AUDIO DIRECTION" in sections:
        _check_speech(text, audio_text, errors)

    shot_count = 0
    if "SHOT LIST" in sections:
        shot_count = _check_shots(sections["SHOT LIST"], expected_duration, errors, warnings)

    if "REFERENCE MAP" in sections and "SHOT LIST" in sections:
        _check_image_references(
            "\n".join(sections["REFERENCE MAP"]),
            "\n".join(sections["SHOT LIST"]),
            image_count,
            errors,
        )

    return PreflightResult(
        ok=not errors,
        errors=tuple(errors),
        warnings=tuple(warnings),
        shot_count=shot_count,
        caption_count=caption_count,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate a beat-synced commercial video prompt before generation.",
    )
    parser.add_argument("--prompt-file", required=True, help="Path to plain-text prompt file")
    parser.add_argument(
        "--image-count",
        type=int,
        default=0,
        help="Expected number of @Image N references (0 skips count enforcement)",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=15,
        help="Expected total video duration in seconds (-1 skips end-time check)",
    )
    parser.add_argument(
        "--mode",
        choices=("block", "warn"),
        default="block",
        help="block exits non-zero on error (default); warn prints findings and exits 0",
    )
    parser.add_argument("--json", action="store_true", help="Emit structured JSON report to stdout")
    args = parser.parse_args(argv)

    if args.image_count < 0:
        print(f"Error: --image-count must be >= 0, got {args.image_count}", file=sys.stderr)
        return 1
    if args.duration != -1 and args.duration <= 0:
        print(f"Error: --duration must be a positive integer or -1, got {args.duration}", file=sys.stderr)
        return 1

    prompt_path = Path(args.prompt_file)
    if not prompt_path.is_file():
        print(f"Error: prompt file not found: {prompt_path}", file=sys.stderr)
        return 1

    text = prompt_path.read_text(encoding="utf-8-sig")
    result = validate_prompt(
        text,
        image_count=args.image_count,
        expected_duration=args.duration,
    )

    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        for warning in result.warnings:
            print(f"WARNING: {warning}", file=sys.stderr)
        if result.ok:
            print(f"Preflight PASSED (shots={result.shot_count}, captions={result.caption_count})")
        else:
            for err in result.errors:
                print(f"ERROR: {err}", file=sys.stderr)

    if not result.ok and args.mode == "block":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
