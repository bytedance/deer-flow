"""CLI failures must be visible to the sandbox as failed shell commands."""

import json
import os
import subprocess
import sys
from pathlib import Path


SKILLS = Path(__file__).resolve().parents[2] / "skills" / "public"


def test_image_cli_missing_credentials_exits_nonzero(tmp_path):
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("A deer", encoding="utf-8")
    output = tmp_path / "slide.png"
    env = os.environ.copy()
    for name in ("GEMINI_API_KEY", "MINIMAX_API_KEY", "IMAGE_GENERATION_API_KEY"):
        env.pop(name, None)
    env["IMAGE_GENERATION_PROVIDER"] = "openai"

    result = subprocess.run(
        [
            sys.executable,
            str(SKILLS / "image-generation" / "scripts" / "generate.py"),
            "--prompt-file",
            str(prompt),
            "--output-file",
            str(output),
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "IMAGE_PROVIDER_NOT_CONFIGURED" in result.stderr
    assert "IMAGE_GENERATION_API_KEY" in result.stderr
    assert not output.exists()


def test_ppt_cli_missing_slide_exits_nonzero(tmp_path):
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"slides": [{"title": "One"}]}), encoding="utf-8")
    output = tmp_path / "deck.pptx"
    result = subprocess.run(
        [
            sys.executable,
            str(SKILLS / "ppt-generation" / "scripts" / "generate.py"),
            "--plan-file",
            str(plan),
            "--slide-images",
            str(tmp_path / "missing.png"),
            "--output-file",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "PPT_INPUT_MISSING" in result.stderr
    assert "Slide image not found" in result.stderr
    assert not output.exists()


def test_ppt_cli_rejects_missing_page_before_writing_output(tmp_path):
    plan = tmp_path / "plan.json"
    plan.write_text(
        json.dumps({"slides": [{"title": "One"}, {"title": "Two"}]}),
        encoding="utf-8",
    )
    output = tmp_path / "deck.pptx"
    result = subprocess.run(
        [
            sys.executable,
            str(SKILLS / "ppt-generation" / "scripts" / "generate.py"),
            "--plan-file",
            str(plan),
            "--slide-images",
            str(tmp_path / "slide-one.png"),
            "--output-file",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "PPT_INVALID_INPUT" in result.stderr
    assert "Expected 2 slide images, received 1" in result.stderr
    assert not output.exists()


def test_ppt_cli_composes_complete_deck(tmp_path):
    from PIL import Image
    from pptx import Presentation

    plan = tmp_path / "plan.json"
    plan.write_text(
        json.dumps(
            {"aspect_ratio": "16:9", "slides": [{"title": "One"}, {"title": "Two"}]}
        ),
        encoding="utf-8",
    )
    images = [tmp_path / "slide-1.png", tmp_path / "slide-2.png"]
    for index, path in enumerate(images):
        Image.new("RGB", (320, 180), (index * 100, 50, 180)).save(path)
    output = tmp_path / "deck.pptx"
    result = subprocess.run(
        [
            sys.executable,
            str(SKILLS / "ppt-generation" / "scripts" / "generate.py"),
            "--plan-file",
            str(plan),
            "--slide-images",
            *(str(path) for path in images),
            "--output-file",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert len(Presentation(output).slides) == 2
