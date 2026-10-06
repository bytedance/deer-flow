"""Screen-text leg (spec 2026-09-08 §2/§8, plan Task 5; VLM route 2026-09-30).

第四条腿（ocr）的执行层：读镜头中帧的屏幕文字，写进卡片第三行。

**2026-09-30 起走 `rag.vlm_model`（与 caption 同一条链）**——不再依赖进程内的
PaddleOCR：那条路本机/CI 都没装、装上也没校准过返回形状，而同一个 VLM 读屏幕文字
当天就能用（实测：中英混排四行逐字全对，0.7–3.4 s/帧）。收益是**零新增依赖、零新增
配置**（用户在设置页不需要再管一个 OCR 模型），代价是屏幕文字从"确定性引擎"变成
生成式输出，且会像 caption 一样遇到网络/凭据失败。

降级（spec §2）：屏幕文字是**可选增强**——单镜头失败 → 该镜头「（无）」，绝不阻断
镜头卡；失败率 > 30% 由共用骨架标 degraded，本腿打一条 warning 说清（它没有自己的
`path_status` 腿，与 caption 的状态面不同）。
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping, Sequence

import httpx

from deerflow.knowledge.video.captioner import CaptionOutcome, run_shot_prompt

logger = logging.getLogger(__name__)

#: 屏幕文字的提问方式：要的是**转录**，不是描述（caption 腿那句是双模式，这一句单一）。
_SCREEN_TEXT_PROMPT = "完整转录画面中的全部文字，保留原有换行。如果画面里没有文字，只输出空内容。不要描述画面、不要解释、不要添加任何格式。"


def normalize_ocr_text(lines: Iterable[str]) -> str:
    """OCR 结果清洗拼接纯函数：逐行 strip、丢弃空行、按输入序换行拼接；空 → 空串。

    不改行序（阅读顺序由引擎／模型给出）；空串表示该帧无屏幕文字（spec §2「（无）」）。
    """
    cleaned = [line.strip() for line in lines]
    return "\n".join(text for text in cleaned if text)


async def screen_text_shots(
    shot_frames: Mapping[int, Sequence[bytes]],
    *,
    client: httpx.AsyncClient | None = None,
    model: str | None = None,
) -> CaptionOutcome:
    """按镜头读屏幕文字（每镜头一帧）；降级语义与 caption 腿共用同一套骨架。

    返回值的字段名沿用 ``captions``（两条腿共用 ``run_shot_prompt`` 的骨架）——
    屏幕文字腿读的就是它；``failed`` / ``degraded`` 同义。
    """
    outcome = await run_shot_prompt(shot_frames, prompt=_SCREEN_TEXT_PROMPT, client=client, model=model, what="屏幕文字")
    return CaptionOutcome(
        captions={index: normalize_ocr_text(text.splitlines()) for index, text in outcome.captions.items()},
        failed=outcome.failed,
        degraded=outcome.degraded,
    )
