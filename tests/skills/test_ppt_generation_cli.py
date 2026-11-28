"""The ppt-generation CLI contract: a failure is nonzero and stdout stays clean."""

import json
import subprocess
import sys
from pathlib import Path

from PIL import Image

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "skills/public/ppt-generation/scripts/generate.py"
)


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


def assert_failure(
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


def test_success_exits_zero_and_writes_the_presentation(tmp_path):
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


def test_missing_slide_image_keeps_an_existing_output(tmp_path):
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

    assert_failure(result, "Slide image not found")
    assert output.read_bytes() == b"previous deck"


def test_missing_plan_exits_one(tmp_path):
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

    assert_failure(result, "No such file", output)


def test_invalid_json_plan_exits_one(tmp_path):
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

    assert_failure(result, "Expecting", output)


def test_non_object_plan_exits_one(tmp_path):
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

    assert_failure(result, "has no attribute 'get'", output)


def test_non_object_slide_metadata_exits_one(tmp_path):
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

    assert_failure(result, "has no attribute 'get'", output)


def test_non_image_slide_exits_one(tmp_path):
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

    assert_failure(result, "cannot identify image file", output)


def test_output_path_directory_exits_one(tmp_path):
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


def test_missing_required_argument_is_not_swallowed(tmp_path):
    result = run_cli("--slide-images", str(tmp_path / "slide.png"))

    assert result.returncode == 2
    assert "required" in result.stderr
