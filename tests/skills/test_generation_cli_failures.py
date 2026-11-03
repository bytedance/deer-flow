"""CLI failures must be visible to the sandbox as failed shell commands."""

import json
import os
import runpy
import subprocess
import sys
from pathlib import Path
from zipfile import BadZipFile

import pytest
from PIL import Image
from pptx.presentation import Presentation as PresentationClass


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
    output.write_bytes(b"previous deck")
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
    assert not list(tmp_path.glob(".deck.pptx.*"))


def test_ppt_save_failure_preserves_existing_deck(tmp_path, monkeypatch):
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"slides": [{"title": "One"}]}), encoding="utf-8")
    image = tmp_path / "slide.png"
    Image.new("RGB", (32, 18), "blue").save(image)
    output = tmp_path / "deck.pptx"
    output.write_bytes(b"previous complete deck")
    saved_paths = []

    def fail_during_save(self, path):
        saved_paths.append(Path(path))
        Path(path).write_bytes(b"partial deck")
        raise OSError("disk full during save")

    monkeypatch.setattr(PresentationClass, "save", fail_during_save)
    generate_ppt = runpy.run_path(
        str(SKILLS / "ppt-generation" / "scripts" / "generate.py")
    )["generate_ppt"]

    with pytest.raises(OSError, match="disk full during save"):
        generate_ppt(str(plan), [str(image)], str(output))

    assert saved_paths and saved_paths[0] != output
    assert saved_paths[0].parent == output.parent
    assert output.read_bytes() == b"previous complete deck"
    assert not saved_paths[0].exists()


def test_ppt_invalid_saved_deck_preserves_existing_deck(tmp_path, monkeypatch):
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"slides": [{"title": "One"}]}), encoding="utf-8")
    image = tmp_path / "slide.png"
    Image.new("RGB", (32, 18), "blue").save(image)
    output = tmp_path / "deck.pptx"
    output.write_bytes(b"previous complete deck")

    def save_invalid_deck(self, path):
        Path(path).write_bytes(b"not a PPTX")

    monkeypatch.setattr(PresentationClass, "save", save_invalid_deck)
    generate_ppt = runpy.run_path(
        str(SKILLS / "ppt-generation" / "scripts" / "generate.py")
    )["generate_ppt"]

    with pytest.raises(BadZipFile):
        generate_ppt(str(plan), [str(image)], str(output))

    assert output.read_bytes() == b"previous complete deck"
    assert not list(tmp_path.glob(".deck.pptx.*"))
