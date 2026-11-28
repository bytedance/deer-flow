"""Offline unit tests for video-generation prompt preflight validator."""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_DIR = REPO_ROOT / "skills" / "public" / "video-generation"
PREFLIGHT_PATH = SKILL_DIR / "scripts" / "preflight.py"
TEMPLATE_PATH = SKILL_DIR / "templates" / "commercial-short-ad.md"


def _load_preflight():
    spec = importlib.util.spec_from_file_location("video_generation_preflight", PREFLIGHT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["video_generation_preflight"] = module
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


preflight = _load_preflight()


def _extract_worked_example() -> str:
    content = TEMPLATE_PATH.read_text(encoding="utf-8-sig")
    blocks = re.findall(r"```text\r?\n(.*?)\r?\n```", content, re.DOTALL)
    assert len(blocks) >= 2, "Expected template block and worked example block in commercial-short-ad.md"
    return blocks[-1]


def test_worked_example_in_template_passes_preflight():
    example = _extract_worked_example()
    result = preflight.validate_prompt(example, image_count=2, expected_duration=15)
    assert result.ok, f"Expected worked example to pass, got errors: {result.errors}"
    assert result.warnings == ()
    assert result.shot_count == 8
    assert result.caption_count == 2


def test_multi_shot_short_clip_passes_without_15s_shot_warning():
    prompt = """CHARACTER DIRECTION
A creator in a clean linen shirt at a sunlit studio desk, relaxed posture.
REFERENCE MAP
@Image 1 = hero ceramic mug front angle
ENVIRONMENT
Bright modern kitchen counter at morning, soft window light, clean editorial grade.
AUDIO DIRECTION
Continuous original BGM at 120 BPM, warm acoustic guitar groove, playing from 0s to 6s. SPEECH INVENTORY: 0 on-camera lip-synced lines and 0 voiceover lines.
SHOT LIST
0s-3s (shot 1, cut on downbeat of bar 1): 35mm slow push-in as steam rises from the ceramic mug @Image 1 in soft window light. (acoustic groove enters) <gentle pour>
3s-6s (shot 2, cut on downbeat of bar 3): 50mm locked-off hero frame of @Image 1 on the counter, sunlit shadow behind. 【Brew slower】 (melody resolves on final downbeat)
CONTINUITY AND PRODUCT CONSISTENCY
Keep the matte ceramic finish and proportions of @Image 1 identical in both shots.
"""
    result = preflight.validate_prompt(prompt, image_count=1, expected_duration=6)
    assert result.ok, f"Unexpected errors: {result.errors}"
    assert result.warnings == ()
    assert result.shot_count == 2
    assert result.caption_count == 1


def test_auto_duration_skips_end_time_check():
    example = _extract_worked_example()
    result = preflight.validate_prompt(example, image_count=2, expected_duration=-1)
    assert result.ok
    assert result.shot_count == 8


def test_blocks_banned_terms_camera_brands_negative_music_and_emoji():
    example = _extract_worked_example()
    bad = (
        example.replace("Kodak Portra 400", "ARRI Alexa 8K stunning masterpiece 唯美 🔥")
        .replace("(groove continues)", "(no music, ambient only)")
    )
    result = preflight.validate_prompt(bad, image_count=2, expected_duration=15)
    assert not result.ok
    joined = "\n".join(result.errors).lower()
    assert "arri" in joined
    assert "8k" in joined
    assert "stunning" in joined
    assert "唯美" in joined
    assert "no music" in joined
    assert "emoji" in joined


def test_rejects_json_markdown_bullets_empty_and_duplicate_sections():
    assert not preflight.validate_prompt("").ok

    json_res = preflight.validate_prompt('{"prompt": "hello"}')
    assert not json_res.ok
    assert any("not JSON" in err for err in json_res.errors)

    example = _extract_worked_example()
    bullet_res = preflight.validate_prompt(
        example.replace("0s-2s (shot 1", "- 0s-2s (shot 1"),
        image_count=2,
        expected_duration=15,
    )
    assert not bullet_res.ok
    assert any("not Markdown list or JSON" in err for err in bullet_res.errors)

    dup_res = preflight.validate_prompt(example + "\nENVIRONMENT\nExtra section\n", image_count=2, expected_duration=15)
    assert not dup_res.ok
    assert any("Duplicate section header: ENVIRONMENT" in err for err in dup_res.errors)


def test_blocks_timecode_gap_wrong_duration_and_missing_music_cue():
    example = _extract_worked_example()
    bad_time = example.replace("12s-15s", "13s-16s")
    res = preflight.validate_prompt(bad_time, image_count=2, expected_duration=15)
    assert not res.ok
    joined = "\n".join(res.errors)
    assert "timecode gap/overlap" in joined
    assert "ends at 16s, expected 15s" in joined

    no_cue = example.replace("(groove continues)", "")
    res2 = preflight.validate_prompt(no_cue, image_count=2, expected_duration=15)
    assert not res2.ok
    assert any("missing a '(music cue)'" in err for err in res2.errors)


def test_blocks_missing_unused_and_out_of_range_image_references():
    example = _extract_worked_example()
    missing_third = preflight.validate_prompt(example, image_count=3, expected_duration=15)
    assert not missing_third.ok
    joined = "\n".join(missing_third.errors)
    assert "REFERENCE MAP is missing declaration(s): @Image 3" in joined
    assert "SHOT LIST must reference every image at least once; missing: @Image 3" in joined

    out_of_range = preflight.validate_prompt(example, image_count=1, expected_duration=15)
    assert not out_of_range.ok
    assert any("Out-of-range image reference(s)" in err and "@Image 2" in err for err in out_of_range.errors)


def test_blocks_caption_count_and_en_zh_budget_overflow():
    example = _extract_worked_example()
    over_en = example.replace(
        "【Morning, on repeat】",
        "【This caption definitely has way too many words inside】",
    )
    res_en = preflight.validate_prompt(over_en, image_count=2, expected_duration=15)
    assert not res_en.ok
    assert any("exceeds English budget" in err for err in res_en.errors)

    over_zh = example.replace("【Morning, on repeat】", "【这是一段明显超过十个字的中文标题文案】")
    res_zh = preflight.validate_prompt(over_zh, image_count=2, expected_duration=15)
    assert not res_zh.ok
    assert any("exceeds Chinese budget" in err for err in res_zh.errors)

    too_many = example.replace("<whoosh>", "<whoosh> 【Extra one】 【Extra two】")
    res_count = preflight.validate_prompt(too_many, image_count=2, expected_duration=15)
    assert not res_count.ok
    assert any("Too many captions" in err for err in res_count.errors)


def test_blocks_speech_inventory_violations_and_budget_overflow():
    example = _extract_worked_example()

    missing_inv = example.replace("SPEECH INVENTORY: 0 on-camera lip-synced lines and 0 voiceover lines.", "")
    res_missing = preflight.validate_prompt(missing_inv, image_count=2, expected_duration=15)
    assert not res_missing.ok
    assert any("SPEECH INVENTORY:" in err for err in res_missing.errors)

    stray_braces = example.replace("<whoosh>", "<whoosh> {unwanted}")
    res_braces = preflight.validate_prompt(stray_braces, image_count=2, expected_duration=15)
    assert not res_braces.ok
    assert any("Curly braces" in err for err in res_braces.errors)

    over_vo = example.replace(
        "SPEECH INVENTORY: 0 on-camera lip-synced lines and 0 voiceover lines.",
        "SPEECH INVENTORY: 0 on-camera lip-synced lines and 1 voiceover lines.",
    ).replace(
        "(groove continues, plucked synth melody)",
        "Voiceover: one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen (groove continues, plucked synth melody)",
    )
    res_vo = preflight.validate_prompt(over_vo, image_count=2, expected_duration=15)
    assert not res_vo.ok
    assert any("Spoken lines exceed English budget" in err for err in res_vo.errors)


def test_rejects_invalid_numeric_parameters():
    example = _extract_worked_example()
    with pytest.raises(ValueError, match="image_count"):
        preflight.validate_prompt(example, image_count=-1)
    with pytest.raises(ValueError, match="expected_duration"):
        preflight.validate_prompt(example, expected_duration=0)
    with pytest.raises(ValueError, match="expected_duration"):
        preflight.validate_prompt(example, expected_duration=-2)


def test_cli_block_warn_json_and_error_exit_codes(tmp_path, capsys):
    bad_prompt = tmp_path / "bad.txt"
    bad_prompt.write_text("SHOT LIST\nnot a valid shot", encoding="utf-8")

    rc_block = preflight.main(["--prompt-file", str(bad_prompt), "--mode", "block"])
    captured = capsys.readouterr()
    assert rc_block == 1
    assert "ERROR:" in captured.err

    rc_warn = preflight.main(["--prompt-file", str(bad_prompt), "--mode", "warn"])
    captured = capsys.readouterr()
    assert rc_warn == 0
    assert "ERROR:" in captured.err

    good_prompt = tmp_path / "good.txt"
    good_prompt.write_text(_extract_worked_example(), encoding="utf-8")
    rc_json = preflight.main(["--prompt-file", str(good_prompt), "--image-count", "2", "--duration", "15", "--json"])
    captured = capsys.readouterr()
    assert rc_json == 0
    payload = json.loads(captured.out)
    assert payload["ok"] is True
    assert payload["shot_count"] == 8
    assert payload["caption_count"] == 2

    assert preflight.main(["--prompt-file", str(tmp_path / "missing.txt")]) == 1
    assert preflight.main(["--prompt-file", str(good_prompt), "--image-count", "-1"]) == 1
    assert preflight.main(["--prompt-file", str(good_prompt), "--duration", "0"]) == 1


def test_video_generation_skill_scripts_preserve_skillscan_hygiene():
    preflight_src = (SKILL_DIR / "scripts" / "preflight.py").read_text(encoding="utf-8")
    assert "subprocess" not in preflight_src
    assert "shell=True" not in preflight_src

    for rel in (
        "SKILL.md",
        "AGENTS.md",
        "templates/commercial-short-ad.md",
        "scripts/preflight.py",
        "scripts/stitch.sh",
    ):
        raw = (SKILL_DIR / rel).read_bytes()
        assert b"\x00" not in raw
        text = raw.decode("utf-8")
        for token_prefix in ("AKIA", "AKLT", "ghp_", "AIza"):
            assert token_prefix not in text, f"Unexpected credential-like prefix {token_prefix!r} in {rel}"
