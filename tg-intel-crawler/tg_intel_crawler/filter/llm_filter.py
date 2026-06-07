import json
import logging
from dataclasses import dataclass, field
from typing import Optional

from openai import AsyncOpenAI

logger = logging.getLogger("tg_crawler")


@dataclass
class AnalysisResult:
    """Result of LLM analysis for a single message."""

    is_relevant: bool = False
    risk_type: str = ""
    risk_level: str = ""
    entities: dict = field(default_factory=dict)
    summary: str = ""


class LLMFilter:
    """LLM-based secondary filter using AsyncOpenAI-compatible API."""

    SYSTEM_PROMPT = """你是一个黑灰产情报分析专家。你需要分析以下消息是否与字节跳动/抖音/TikTok相关的黑灰产活动有关。

对每条消息，返回JSON数组，每个元素包含：
- index: 消息序号（从0开始）
- is_relevant: bool，是否与字节跳动黑灰产相关
- risk_type: 风险类型（账号交易/刷量作弊/引流诈骗/数据泄露/工具交易/其他），不相关则为空
- risk_level: 风险等级（high/medium/low），判定标准如下：
  - high: 直接提供黑灰产服务/交易（明确的买卖、接单、报价、招募），或涉及数据泄露/安全漏洞
  - medium: 分享黑灰产方法/教程/工具，或疑似在试探/招揽但未明确报价
  - low: 仅讨论/提及相关话题，未提供具体服务或交易信息
- entities: 提取的实体对象，包含：
  - accounts: 涉及的平台账号列表
  - contacts: 联系方式列表，每项格式为 "平台:联系方式"，例如 "QQ:3908344109", "Telegram:@smmmaxx1", "微信:wx_abc123", "WhatsApp:+8613800138000"
  - links: 链接列表
  - tools: 工具/软件列表
  - prices: 价格信息列表
- summary: 一句话中文摘要，不相关则为空

注意：contacts字段必须标注平台来源（QQ/微信/Telegram/WhatsApp/手机/邮箱等），格式为"平台:具体联系方式"。

只返回JSON数组，不要其他内容。"""

    def __init__(self, config: dict):
        self._client = AsyncOpenAI(
            api_key=config["api_key"],
            base_url=config["base_url"],
        )
        self._model = config["model"]
        self._batch_size = config.get("batch_size", 15)

    @staticmethod
    def _build_prompt(messages: list[str]) -> str:
        """Build the user prompt with numbered messages."""
        lines = []
        for i, msg in enumerate(messages):
            lines.append(f"[{i}] {msg}")
        return "请分析以下消息:\n\n" + "\n".join(lines)

    @staticmethod
    def _parse_response(response_text: str) -> list[AnalysisResult]:
        """Parse LLM JSON response into AnalysisResult objects."""
        try:
            text = response_text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1]
                text = text.rsplit("```", 1)[0]

            data = json.loads(text)
            results = []
            for item in data:
                results.append(AnalysisResult(
                    is_relevant=item.get("is_relevant", False),
                    risk_type=item.get("risk_type", ""),
                    risk_level=item.get("risk_level", ""),
                    entities=item.get("entities", {}),
                    summary=item.get("summary", ""),
                ))
            return results
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.error(f"Failed to parse LLM response: {e}")
            return []

    async def analyze_batch(self, messages: list[str]) -> list[AnalysisResult]:
        """Send a batch of messages to LLM for analysis."""
        if not messages:
            return []

        prompt = self._build_prompt(messages)

        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
            )
            content = response.choices[0].message.content
            return self._parse_response(content)
        except Exception as e:
            logger.error(f"LLM API call failed: {e}")
            return []

    async def analyze(self, messages: list[str]) -> list[AnalysisResult]:
        """Analyze messages in batches."""
        all_results = []
        for i in range(0, len(messages), self._batch_size):
            batch = messages[i : i + self._batch_size]
            results = await self.analyze_batch(batch)
            all_results.extend(results)
        return all_results
