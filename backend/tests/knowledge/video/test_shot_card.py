"""Shot-card assembly pure-function tests (spec 2026-09-08 §3/§6, plan Task 6).

卡文本组装是 spec §3 的**冻结契约**：正文模板逐字钉死（嵌入文本 = 存储文本 =
正文，不含时间码头）；时间码 HH:MM:SS.mmm 往返；三模式 card_text_mode 消融；
全空镜头判 empty（不产 chunk）；render_card_display 展示层合成带头全卡（单一源）。
纯函数，全本机可测、无 skipif。
"""

from __future__ import annotations

import pytest

from deerflow.knowledge.video.shot_card import (
    assemble_card_body,
    chunk_id_for_shot,
    format_timecode,
    heading_path_for_shot,
    is_empty_card,
    parse_timecode,
    render_card_display,
)

# ── 时间码 HH:MM:SS.mmm 往返 ─────────────────────────────────────────────


def test_format_timecode():
    assert format_timecode(0) == "00:00:00.000"
    assert format_timecode(72000) == "00:01:12.000"
    assert format_timecode(3723456) == "01:02:03.456"


def test_parse_timecode():
    assert parse_timecode("00:01:12.000") == 72000
    assert parse_timecode("01:02:03.456") == 3723456
    assert parse_timecode("00:00:00.000") == 0


@pytest.mark.parametrize("ms", [0, 1, 999, 1000, 59999, 60000, 72000, 3600000, 3723456])
def test_timecode_round_trip(ms):
    assert parse_timecode(format_timecode(ms)) == ms


# ── chunk_id / heading_path（spec §3 扁平序 + 展示层）─────────────────────


def test_chunk_id_for_shot():
    assert chunk_id_for_shot("doc1", 0) == "doc1#0000"
    assert chunk_id_for_shot("doc1", 2) == "doc1#0002"
    assert chunk_id_for_shot("abc", 123) == "abc#0123"


def test_heading_path_for_shot():
    assert heading_path_for_shot("clip.mp4", 2) == ["clip.mp4", "镜头 #2"]


# ── assemble_card_body：冻结模板（spec §3）────────────────────────────────


def test_assemble_card_body_full_template_verbatim():
    """正文模板逐字钉死：全角冒号、三段顺序、换行分隔（嵌入文本单一源）。"""
    body = assemble_card_body(caption="讲师在白板前讲解", asr_text="今天我们讲向量检索", ocr_text="向量检索原理")
    assert body == "场景：讲师在白板前讲解\n口述：今天我们讲向量检索\n屏幕文字：向量检索原理"


def test_assemble_card_body_full_all_empty_uses_placeholder():
    """三路俱空 → 三段皆（无）；模板三行恒定（caption 空补（无），保持稳定结构）。"""
    assert assemble_card_body(caption="", asr_text="", ocr_text="") == "场景：（无）\n口述：（无）\n屏幕文字：（无）"


def test_assemble_card_body_full_partial():
    body = assemble_card_body(caption="演示操作", asr_text="", ocr_text="设置面板")
    assert body == "场景：演示操作\n口述：（无）\n屏幕文字：设置面板"


def test_assemble_card_body_caption_only_mode():
    """消融模式 caption_only：只场景行（spec §6 描述质量消融）。"""
    body = assemble_card_body(caption="讲师讲解", asr_text="口述内容", ocr_text="屏幕文字", mode="caption_only")
    assert body == "场景：讲师讲解"


def test_assemble_card_body_asr_only_mode():
    """消融模式 asr_only：只口述行（spec §6）。"""
    body = assemble_card_body(caption="讲师讲解", asr_text="口述内容", ocr_text="屏幕文字", mode="asr_only")
    assert body == "口述：口述内容"


# ── is_empty_card：全空镜头判定（不产 chunk）──────────────────────────────


def test_is_empty_card_all_blank():
    assert is_empty_card(caption="", asr_text="", ocr_text="") is True
    assert is_empty_card(caption="  ", asr_text="\n", ocr_text="   ") is True  # strip 后俱空


def test_is_empty_card_any_non_empty():
    assert is_empty_card(caption="描述", asr_text="", ocr_text="") is False
    assert is_empty_card(caption="", asr_text="口述", ocr_text="") is False
    assert is_empty_card(caption="", asr_text="", ocr_text="文字") is False


# ── render_card_display：展示层合成带头全卡（spec §3 嵌入文本契约）────────


def test_render_card_display_prepends_timecode_header():
    """展示头 = 镜头 #K [start – end]（HH:MM:SS.mmm），正文原样接在头下（单一源）。"""
    shot = {"shot_index": 2, "start_ms": 72000, "end_ms": 100000}
    body = "场景：讲师讲解\n口述：（无）\n屏幕文字：（无）"
    assert render_card_display(body, shot) == "镜头 #2 [00:01:12.000 – 00:01:40.000]\n场景：讲师讲解\n口述：（无）\n屏幕文字：（无）"


def test_render_card_display_keeps_body_verbatim():
    """正文原样嵌入尾部（不改一字）：嵌入文本 = 展示正文，验证零双存储一致性。"""
    shot = {"shot_index": 0, "start_ms": 0, "end_ms": 5000}
    body = assemble_card_body(caption="开场", asr_text="你好", ocr_text="")
    rendered = render_card_display(body, shot)
    assert rendered.startswith("镜头 #0 [00:00:00.000 – 00:00:05.000]\n")
    assert rendered.endswith(body)
