"""Record and verify the contiguous slide prefix for a resumable presentation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

from PIL import Image


class ProgressError(ValueError):
    """The recorded deck cannot safely be resumed or composed."""


def _absolute(path: str) -> str:
    if not Path(path).is_absolute():
        raise ProgressError("Plan, progress and slide image paths must be absolute")
    return os.path.abspath(path)


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _image_sha256(path: str) -> str:
    with Image.open(path) as image:
        image.load()
        if image.width < 1 or image.height < 1:
            raise ProgressError(f"Invalid slide image: {path}")
    return _sha256(path)


def _slide_count(plan_file: str) -> int:
    with open(plan_file, encoding="utf-8") as source:
        plan = json.load(source)
    slides = plan.get("slides") if isinstance(plan, dict) else None
    if (
        not isinstance(slides, list)
        or not slides
        or any(not isinstance(slide, dict) for slide in slides)
    ):
        raise ProgressError("Presentation plan must contain a non-empty slides list")
    return len(slides)


def _write_progress(manifest_file: str, record: dict) -> None:
    target = Path(manifest_file)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as output:
            temporary = output.name
            json.dump(record, output, ensure_ascii=False, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, target)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def initialize(
    plan_file: str,
    manifest_file: str,
    slide_images: list[str],
    *,
    restart: bool = False,
) -> dict:
    plan_file = _absolute(plan_file)
    manifest_file = _absolute(manifest_file)
    images = [_absolute(path) for path in slide_images]
    if len(images) != _slide_count(plan_file) or len(set(images)) != len(images):
        raise ProgressError(
            "Slide image paths must be distinct and match the plan's slide count"
        )
    if Path(manifest_file).exists() and not restart:
        raise ProgressError(
            "Progress already exists; inspect it with status or use --restart only after the user chooses to restart"
        )
    record = {
        "version": 1,
        "plan_file": plan_file,
        "plan_sha256": _sha256(plan_file),
        "slide_images": images,
        "completed": {},
    }
    _write_progress(manifest_file, record)
    return status(manifest_file)


def _read_progress(manifest_file: str) -> dict:
    with open(manifest_file, encoding="utf-8") as source:
        record = json.load(source)
    if not isinstance(record, dict) or record.get("version") != 1:
        raise ProgressError("Unsupported presentation progress record")
    plan_file = record.get("plan_file")
    images = record.get("slide_images")
    completed = record.get("completed")
    if (
        not isinstance(plan_file, str)
        or not isinstance(images, list)
        or not images
        or not all(isinstance(path, str) for path in images)
        or len(set(images)) != len(images)
        or not isinstance(completed, dict)
    ):
        raise ProgressError("Invalid presentation progress record")
    if len(images) != _slide_count(plan_file) or record.get("plan_sha256") != _sha256(
        plan_file
    ):
        raise ProgressError(
            "Presentation plan changed; choose restart rather than reusing recorded slides"
        )
    if any(
        not isinstance(key, str)
        or not key.isdigit()
        or not 1 <= int(key) <= len(images)
        or not isinstance(value, str)
        for key, value in completed.items()
    ):
        raise ProgressError("Invalid completed slide records")
    return record


def _valid_prefix(record: dict) -> tuple[int, int | None]:
    completed = record["completed"]
    for number, path in enumerate(record["slide_images"], 1):
        expected = completed.get(str(number))
        if expected is None:
            return number - 1, number if any(
                int(key) > number for key in completed
            ) else None
        try:
            if _image_sha256(path) != expected:
                return number - 1, number
        except (FileNotFoundError, OSError, ValueError):
            return number - 1, number
    return len(record["slide_images"]), None


def status(manifest_file: str) -> dict:
    manifest_file = _absolute(manifest_file)
    record = _read_progress(manifest_file)
    count, invalid_from = _valid_prefix(record)
    total = len(record["slide_images"])
    return {
        "manifest_file": manifest_file,
        "plan_file": record["plan_file"],
        "slide_images": record["slide_images"],
        "total_slides": total,
        "completed_slides": count,
        "next_slide": count + 1 if count < total else None,
        "invalid_from": invalid_from,
    }


def mark_completed(manifest_file: str, slide_number: int) -> dict:
    manifest_file = _absolute(manifest_file)
    record = _read_progress(manifest_file)
    count, _ = _valid_prefix(record)
    if slide_number != count + 1 or slide_number > len(record["slide_images"]):
        raise ProgressError(
            f"Expected slide {count + 1} next; slides must be recorded in order"
        )
    path = record["slide_images"][slide_number - 1]
    record["completed"] = {
        key: value
        for key, value in record["completed"].items()
        if int(key) < slide_number
    }
    record["completed"][str(slide_number)] = _image_sha256(path)
    _write_progress(manifest_file, record)
    return status(manifest_file)


def require_complete(
    manifest_file: str, plan_file: str, slide_images: list[str]
) -> None:
    try:
        record = _read_progress(_absolute(manifest_file))
    except FileNotFoundError as exc:
        raise ProgressError(
            f"Presentation progress record is missing: {manifest_file}"
        ) from exc
    if record["plan_file"] != _absolute(plan_file) or record["slide_images"] != [
        _absolute(path) for path in slide_images
    ]:
        raise ProgressError(
            "Presentation inputs do not match the recorded plan and slide images"
        )
    count, _ = _valid_prefix(record)
    if count != len(slide_images):
        raise ProgressError(
            f"Presentation has only {count} verified slides out of {len(slide_images)}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Track verified slides across PPT generation turns"
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    init = subcommands.add_parser("init")
    init.add_argument("--manifest-file", required=True)
    init.add_argument("--plan-file", required=True)
    init.add_argument("--slide-images", nargs="+", required=True)
    init.add_argument("--restart", action="store_true")
    current = subcommands.add_parser("status")
    current.add_argument("--manifest-file", required=True)
    mark = subcommands.add_parser("mark")
    mark.add_argument("--manifest-file", required=True)
    mark.add_argument("--slide-number", type=int, required=True)
    args = parser.parse_args()
    try:
        if args.command == "init":
            result = initialize(
                args.plan_file,
                args.manifest_file,
                args.slide_images,
                restart=args.restart,
            )
        elif args.command == "mark":
            result = mark_completed(args.manifest_file, args.slide_number)
        else:
            result = status(args.manifest_file)
        print(json.dumps(result, ensure_ascii=False))
    except (
        ProgressError,
        FileNotFoundError,
        OSError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        print(f"Error [PPT_PROGRESS_INVALID]: {exc}", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
