"""Shot-card assembly (spec 2026-09-08 §3/§6, plan Task 6).

materialize 腿的纯函数核心：把镜头的三路原文（caption / asr / ocr）组装为**冻结
卡正文**——这就是 ``chunks.text`` = 嵌入文本 = 存储文本（spec §3 嵌入文本契约，
评审 G2：时间码头不进向量，正文是单一源）。展示层带头全卡由 ``render_card_display``
合成（纯文本导出 / 人审面），与嵌入正文共享同一 body，零双存储。

时间码格式冻结 ``HH:MM:SS.mmm``（毫秒三位，spec §3）；chunk_id 沿用扁平序
``{doc_id}#{shot_index:04d}``（不引入层级地址）；heading_path 仅展示层。

``card_text_mode`` 三模式（spec §6 caption 质量消融）：full（三段）/ caption_only
（只场景）/ asr_only（只口述）——非 full 模式是 recall-test 实验路径，不改 full
的冻结模板。
"""

from __future__ import annotations

from collections.abc import Mapping

#: 全空路的占位符（spec §3 冻结模板）。
_EMPTY = "（无）"


def format_timecode(ms: int) -> str:
    """毫秒 → ``HH:MM:SS.mmm``（spec §3 冻结格式，毫秒三位；负值 clamp 到 0）。

    小时位不截断（超 99h 自然进位为三位以上），覆盖长视频/直播回放。
    """
    total = max(0, int(ms))
    millis = total % 1000
    total_seconds = total // 1000
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"


def parse_timecode(timecode: str) -> int:
    """``HH:MM:SS.mmm`` → 毫秒（``format_timecode`` 的逆，往返一致）；毫秒段可省略。"""
    text = timecode.strip()
    hms, _, millis_part = text.partition(".")
    millis = int(millis_part) if millis_part else 0
    parts = hms.split(":")
    if len(parts) != 3:
        raise ValueError(f"非法时间码（期望 HH:MM:SS.mmm）：{timecode!r}")
    hours, minutes, seconds = (int(part) for part in parts)
    return (hours * 3600 + minutes * 60 + seconds) * 1000 + millis


def chunk_id_for_shot(doc_id: str, shot_index: int) -> str:
    """镜头卡 chunk_id：扁平序 ``{doc_id}#{shot_index:04d}``（spec §3，与 chunk_index 同序）。"""
    return f"{doc_id}#{shot_index:04d}"


def heading_path_for_shot(video_name: str, shot_index: int) -> list[str]:
    """展示层 heading_path：``[视频文件名, 镜头 #K]``（spec §3，不进嵌入语义）。"""
    return [video_name, f"镜头 #{shot_index}"]


def assemble_card_body(*, caption: str, asr_text: str, ocr_text: str, mode: str = "full") -> str:
    """组装冻结卡正文（= ``chunks.text`` = 嵌入文本，spec §3）。

    full 模式逐字模板（全角冒号、换行分隔、空路补（无）保持三行稳定）::

        场景：{caption 或 （无）}
        口述：{asr_text 或 （无）}
        屏幕文字：{ocr_text 或 （无）}

    消融模式（spec §6）：``caption_only`` 只场景行、``asr_only`` 只口述行。改模板
    即改嵌入契约，故被 test_shot_card.py 逐字钉死。
    """
    scene = f"场景：{(caption or '').strip() or _EMPTY}"
    speech = f"口述：{(asr_text or '').strip() or _EMPTY}"
    screen = f"屏幕文字：{(ocr_text or '').strip() or _EMPTY}"
    if mode == "caption_only":
        return scene
    if mode == "asr_only":
        return speech
    return "\n".join([scene, speech, screen])


def is_empty_card(*, caption: str, asr_text: str, ocr_text: str) -> bool:
    """三路原文 strip 后俱空 → True（全空镜头不产 chunk，spec §2 materialize）。"""
    return not (caption or "").strip() and not (asr_text or "").strip() and not (ocr_text or "").strip()


def render_card_display(body: str, shot: Mapping) -> str:
    """展示层合成带头全卡：``镜头 #K [start – end]``（HH:MM:SS.mmm）+ 换行 + 正文原样。

    单一源——纯文本导出 / 人审面用此；``chunks.text`` 只存 body（无头），故嵌入正文
    与展示正文完全一致（spec §3 嵌入文本契约，零双存储）。``shot`` 取自 video_shots
    行（shot_index / start_ms / end_ms）。
    """
    start = format_timecode(int(shot["start_ms"]))
    end = format_timecode(int(shot["end_ms"]))
    header = f"镜头 #{shot['shot_index']} [{start} – {end}]"
    return f"{header}\n{body}"
