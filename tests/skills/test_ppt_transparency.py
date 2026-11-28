"""Slide composition: embedded image handling and the CLI failure contract."""

import json
import runpy
import subprocess
import sys
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image
from pptx import Presentation

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "skills/public/ppt-generation/scripts/generate.py"
)


@pytest.mark.parametrize("mode", ["RGBA", "LA", "P", "RGB", "L"])
def test_ppt_preserves_png_transparency(tmp_path, mode):
    source = tmp_path / "slide.png"
    if mode == "P":
        image = Image.new("P", (64, 64), 0)
        image.putpalette([0, 0, 0, 240, 80, 40] + [0] * 762)
        image.putpixel((48, 32), 1)
        image.save(source, transparency=0)
    elif mode in {"RGB", "L"}:
        image = Image.new(mode, (64, 64), 0)
        image.putpixel((48, 32), (240, 80, 40) if mode == "RGB" else 160)
        image.save(source, transparency=(0, 0, 0) if mode == "RGB" else 0)
    else:
        image = Image.new(mode, (64, 64), (0, 0, 0, 0) if mode == "RGBA" else (0, 0))
        image.putpixel((48, 32), (240, 80, 40, 128) if mode == "RGBA" else (160, 128))
        image.save(source)
    image.close()
    with Image.open(source) as original:
        expected = original.convert("RGBA")

    plan = tmp_path / "plan.json"
    plan.write_text(
        json.dumps({"slides": [{"title": "Transparent slide"}]}), encoding="utf-8"
    )
    output = tmp_path / "slides.pptx"
    generate_ppt = runpy.run_path(str(SCRIPT))["generate_ppt"]

    generate_ppt(str(plan), [str(source)], str(output))

    presentation = Presentation(output)
    picture = presentation.slides[0].shapes[0]
    with Image.open(BytesIO(picture.image.blob)) as embedded:
        assert embedded.format == "PNG"
        assert embedded.convert("RGBA").tobytes() == expected.tobytes()
    assert (
        "Title: Transparent slide"
        in presentation.slides[0].notes_slide.notes_text_frame.text
    )


@pytest.mark.parametrize("mode", ["RGB", "L", "P"])
def test_ppt_keeps_opaque_images_as_jpeg(tmp_path, mode):
    source = tmp_path / "slide.png"
    with Image.new(mode, (64, 64), 100) as image:
        image.save(source)
    plan = tmp_path / "plan.json"
    plan.write_text("{}", encoding="utf-8")
    output = tmp_path / "slides.pptx"

    runpy.run_path(str(SCRIPT))["generate_ppt"](str(plan), [str(source)], str(output))

    picture = Presentation(output).slides[0].shapes[0]
    with Image.open(BytesIO(picture.image.blob)) as embedded:
        assert embedded.format == "JPEG"
        assert embedded.size == (64, 64)


# The CLI must report composition failures through its exit status: callers
# present the output file when the command succeeds.


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-B", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        timeout=60,
    )


def write_plan(path: Path, plan: object) -> None:
    path.write_text(json.dumps(plan), encoding="utf-8")


def write_image(path: Path) -> None:
    Image.new("RGB", (64, 36), "red").save(path)


def assert_cli_failure(
    result: subprocess.CompletedProcess[str],
    diagnostic: str,
    output: Path | None = None,
) -> None:
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.startswith("Error while generating presentation: ")
    assert diagnostic in result.stderr
    if output is not None:
        assert not output.exists()


def test_cli_success_exits_zero_and_writes_the_presentation(tmp_path):
    plan = tmp_path / "plan.json"
    write_plan(
        plan, {"aspect_ratio": "16:9", "slides": [{"title": "Quarterly report"}]}
    )
    image = tmp_path / "slide.png"
    write_image(image)
    output = tmp_path / "deck.pptx"

    result = run_cli(
        "--plan-file",
        str(plan),
        "--slide-images",
        str(image),
        "--output-file",
        str(output),
    )

    assert result.returncode == 0, result.stderr
    assert "Successfully generated presentation" in result.stdout
    assert result.stderr == ""
    assert output.read_bytes().startswith(b"PK")


def test_cli_missing_slide_image_keeps_an_existing_output(tmp_path):
    plan = tmp_path / "plan.json"
    write_plan(plan, {"slides": [{"title": "One"}]})
    output = tmp_path / "deck.pptx"
    output.write_bytes(b"previous deck")

    result = run_cli(
        "--plan-file",
        str(plan),
        "--slide-images",
        str(tmp_path / "missing.png"),
        "--output-file",
        str(output),
    )

    assert_cli_failure(result, "Slide image not found")
    assert output.read_bytes() == b"previous deck"


def test_cli_missing_plan_exits_one(tmp_path):
    image = tmp_path / "slide.png"
    write_image(image)
    output = tmp_path / "deck.pptx"

    result = run_cli(
        "--plan-file",
        str(tmp_path / "missing.json"),
        "--slide-images",
        str(image),
        "--output-file",
        str(output),
    )

    assert_cli_failure(result, "No such file", output)


def test_cli_invalid_json_plan_exits_one(tmp_path):
    plan = tmp_path / "plan.json"
    plan.write_text("{", encoding="utf-8")
    image = tmp_path / "slide.png"
    write_image(image)
    output = tmp_path / "deck.pptx"

    result = run_cli(
        "--plan-file",
        str(plan),
        "--slide-images",
        str(image),
        "--output-file",
        str(output),
    )

    assert_cli_failure(result, "Expecting", output)


def test_cli_non_object_plan_exits_one(tmp_path):
    plan = tmp_path / "plan.json"
    write_plan(plan, ["not", "a", "mapping"])
    image = tmp_path / "slide.png"
    write_image(image)
    output = tmp_path / "deck.pptx"

    result = run_cli(
        "--plan-file",
        str(plan),
        "--slide-images",
        str(image),
        "--output-file",
        str(output),
    )

    assert_cli_failure(result, "has no attribute 'get'", output)


def test_cli_non_object_slide_metadata_exits_one(tmp_path):
    plan = tmp_path / "plan.json"
    write_plan(plan, {"slides": ["not-a-mapping"]})
    image = tmp_path / "slide.png"
    write_image(image)
    output = tmp_path / "deck.pptx"

    result = run_cli(
        "--plan-file",
        str(plan),
        "--slide-images",
        str(image),
        "--output-file",
        str(output),
    )

    assert_cli_failure(result, "has no attribute 'get'", output)


def test_cli_non_image_slide_exits_one(tmp_path):
    plan = tmp_path / "plan.json"
    write_plan(plan, {"slides": [{}]})
    image = tmp_path / "slide.png"
    image.write_text("not an image", encoding="utf-8")
    output = tmp_path / "deck.pptx"

    result = run_cli(
        "--plan-file",
        str(plan),
        "--slide-images",
        str(image),
        "--output-file",
        str(output),
    )

    assert_cli_failure(result, "cannot identify image file", output)


def test_cli_output_path_directory_exits_one(tmp_path):
    plan = tmp_path / "plan.json"
    write_plan(plan, {"slides": [{}]})
    image = tmp_path / "slide.png"
    write_image(image)

    result = run_cli(
        "--plan-file",
        str(plan),
        "--slide-images",
        str(image),
        "--output-file",
        str(tmp_path),
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.startswith("Error while generating presentation: ")


def test_cli_missing_required_argument_is_not_swallowed(tmp_path):
    result = run_cli("--slide-images", str(tmp_path / "slide.png"))

    assert result.returncode == 2
    assert "required" in result.stderr
