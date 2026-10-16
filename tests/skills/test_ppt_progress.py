"""A stopped deck resumes only from a verified, plan-bound slide prefix."""

import json
import os
import subprocess
import sys
from pathlib import Path

from PIL import Image
from pptx import Presentation


SCRIPTS = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "public"
    / "ppt-generation"
    / "scripts"
)


def _run(script: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / script), *map(str, args)],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )


def _plan(tmp_path: Path, count: int) -> Path:
    path = tmp_path / "plan.json"
    path.write_text(
        json.dumps(
            {
                "aspect_ratio": "16:9",
                "slides": [
                    {"title": f"Slide {number}"} for number in range(1, count + 1)
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _image(path: Path, color: str) -> None:
    Image.new("RGB", (320, 180), color).save(path)


def test_continue_verifies_prior_pages_and_composes_only_a_complete_deck(tmp_path):
    plan = _plan(tmp_path, 3)
    manifest = tmp_path / "progress.json"
    images = [tmp_path / f"slide-{number}.png" for number in range(1, 4)]
    initialized = _run(
        "progress.py",
        "init",
        "--plan-file",
        plan,
        "--manifest-file",
        manifest,
        "--slide-images",
        *images,
    )
    assert initialized.returncode == 0, initialized.stderr
    assert json.loads(initialized.stdout)["next_slide"] == 1

    for number, color in ((1, "red"), (2, "green")):
        _image(images[number - 1], color)
        marked = _run(
            "progress.py", "mark", "--manifest-file", manifest, "--slide-number", number
        )
        assert marked.returncode == 0, marked.stderr

    # The new turn has a new provider. The first two images remain on the
    # mounted user-data volume; only slide 3 needs generation.
    resumed = _run("progress.py", "status", "--manifest-file", manifest)
    assert json.loads(resumed.stdout)["completed_slides"] == 2
    assert json.loads(resumed.stdout)["next_slide"] == 3
    output = tmp_path / "deck.pptx"
    incomplete = _run(
        "generate.py",
        "--plan-file",
        plan,
        "--slide-images",
        *images,
        "--progress-file",
        manifest,
        "--output-file",
        output,
    )
    assert incomplete.returncode != 0
    assert "PPT_PROGRESS_INVALID" in incomplete.stderr
    assert not output.exists()

    _image(images[2], "blue")
    marked = _run(
        "progress.py", "mark", "--manifest-file", manifest, "--slide-number", 3
    )
    assert marked.returncode == 0, marked.stderr
    complete = _run(
        "generate.py",
        "--plan-file",
        plan,
        "--slide-images",
        *images,
        "--progress-file",
        manifest,
        "--output-file",
        output,
    )
    assert complete.returncode == 0, complete.stderr
    assert len(Presentation(output).slides) == 3


def test_changed_image_invalidates_it_and_all_later_slides(tmp_path):
    plan = _plan(tmp_path, 3)
    manifest = tmp_path / "progress.json"
    images = [tmp_path / f"slide-{number}.png" for number in range(1, 4)]
    assert (
        _run(
            "progress.py",
            "init",
            "--plan-file",
            plan,
            "--manifest-file",
            manifest,
            "--slide-images",
            *images,
        ).returncode
        == 0
    )
    for number, color in enumerate(("red", "green", "blue"), 1):
        _image(images[number - 1], color)
        assert (
            _run(
                "progress.py",
                "mark",
                "--manifest-file",
                manifest,
                "--slide-number",
                number,
            ).returncode
            == 0
        )

    _image(images[1], "yellow")
    current = _run("progress.py", "status", "--manifest-file", manifest)
    assert json.loads(current.stdout)["completed_slides"] == 1
    assert json.loads(current.stdout)["next_slide"] == 2
    assert json.loads(current.stdout)["invalid_from"] == 2

    output = tmp_path / "deck.pptx"
    rejected = _run(
        "generate.py",
        "--plan-file",
        plan,
        "--slide-images",
        *images,
        "--progress-file",
        manifest,
        "--output-file",
        output,
    )
    assert rejected.returncode != 0
    assert not output.exists()

    _image(images[1], "purple")
    assert (
        _run(
            "progress.py", "mark", "--manifest-file", manifest, "--slide-number", 2
        ).returncode
        == 0
    )
    after_mark = json.loads(
        _run("progress.py", "status", "--manifest-file", manifest).stdout
    )
    assert after_mark["completed_slides"] == 2
    assert after_mark["next_slide"] == 3


def test_restart_requires_explicit_flag_and_plan_edits_invalidate_progress(tmp_path):
    plan = _plan(tmp_path, 2)
    manifest = tmp_path / "progress.json"
    images = [tmp_path / "slide-1.png", tmp_path / "slide-2.png"]
    args = ("--plan-file", plan, "--manifest-file", manifest, "--slide-images", *images)
    assert _run("progress.py", "init", *args).returncode == 0
    _image(images[0], "red")
    assert (
        _run(
            "progress.py", "mark", "--manifest-file", manifest, "--slide-number", 1
        ).returncode
        == 0
    )
    assert _run("progress.py", "init", *args).returncode != 0
    assert (
        json.loads(_run("progress.py", "status", "--manifest-file", manifest).stdout)[
            "completed_slides"
        ]
        == 1
    )

    plan.write_text(
        json.dumps({"slides": [{"title": "Edited"}, {"title": "Two"}]}),
        encoding="utf-8",
    )
    assert _run("progress.py", "status", "--manifest-file", manifest).returncode != 0
    restarted = _run("progress.py", "init", *args, "--restart")
    assert restarted.returncode == 0, restarted.stderr
    assert json.loads(restarted.stdout)["completed_slides"] == 0
    assert images[0].exists()  # User files are preserved, but no longer count.
    output = tmp_path / "restarted.pptx"
    incomplete = _run(
        "generate.py",
        "--plan-file",
        plan,
        "--slide-images",
        *images,
        "--progress-file",
        manifest,
        "--output-file",
        output,
    )
    assert incomplete.returncode != 0
    assert not output.exists()


def test_missing_or_corrupt_slide_never_counts_as_completed(tmp_path):
    plan = _plan(tmp_path, 1)
    manifest = tmp_path / "progress.json"
    slide = tmp_path / "slide.png"
    assert (
        _run(
            "progress.py",
            "init",
            "--plan-file",
            plan,
            "--manifest-file",
            manifest,
            "--slide-images",
            slide,
        ).returncode
        == 0
    )
    slide.write_bytes(b"not an image")
    assert (
        _run(
            "progress.py", "mark", "--manifest-file", manifest, "--slide-number", 1
        ).returncode
        != 0
    )
    assert (
        json.loads(_run("progress.py", "status", "--manifest-file", manifest).stdout)[
            "completed_slides"
        ]
        == 0
    )


def test_composition_rejects_a_missing_progress_record(tmp_path):
    plan = _plan(tmp_path, 1)
    slide = tmp_path / "slide.png"
    _image(slide, "red")
    output = tmp_path / "deck.pptx"
    result = _run(
        "generate.py",
        "--plan-file",
        plan,
        "--slide-images",
        slide,
        "--progress-file",
        tmp_path / "missing-progress.json",
        "--output-file",
        output,
    )
    assert result.returncode != 0
    assert "PPT_PROGRESS_INVALID" in result.stderr
    assert not output.exists()
