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

    SYSTEM_PROMPT = """你是一个黑灰产情报分析专家，服务于合法的网络安全研究与平台风控治理。你需要分析以下消息是否与字节跳动/抖音/TikTok相关的黑灰产活动有关。

对每条消息，返回JSON数组，每个元素包含：
- index: 消息序号（从0开始）
- is_relevant: bool，是否与字节跳动黑灰产相关
- risk_type: 风险类型（账号交易/刷量作弊/引流诈骗/数据泄露/工具交易/其他），不相关则为空
- risk_level: 风险等级（high/medium/low），判定标准如下：
  - high: 直接提供黑灰产服务/交易（明确的买卖、接单、报价、招募），或涉及数据泄露/安全漏洞
  - medium: 分享黑灰产方法/教程/工具，或疑似在试探/招揽但未明确报价
  - low: 仅讨论/提及相关话题，未提供具体服务或交易信息
- entities: 提取的实体对象。这是情报核心，必须从原文中**穷尽提取所有出现的实体，不得遗漏、不得脱敏、不得掩码**，保留完整原始值（用于溯源处置）：
  - accounts: 涉及的平台账号列表，保留完整账号名/ID，例如 "抖音号:dy12345", "TikTok:@shopxxx", "小红书:xhs_abc"
  - contacts: 联系方式列表，**逐一提取每一个联系方式**，每项格式为 "平台:联系方式"，平台必须明确标注（QQ/微信/Telegram/WhatsApp/手机/邮箱/钉钉等），例如 "QQ:3908344109", "Telegram:@smmmaxx1", "微信:wx_abc123", "WhatsApp:+8613800138000"。同一条消息出现多个联系方式时全部列出。注意识别变体写法：微信(薇信/VX/v信/weixin)、电报(飞机/纸飞机/TG)、扣扣(QQ)等。
  - links: 所有链接列表，包含完整URL（http/https/t.me/短链等），并保留链接后紧跟的邀请码/口令（如有）
  - domains: 从链接或文本中提取的独立域名列表，例如 "xiaoerhao.com", "北境.top", "fensyun.com"
  - invite_codes: 邀请码/优惠码/口令列表（如"邀请码bbs888"）
  - tools: 工具/软件/平台名称列表
  - prices: 价格信息列表（含金额与单位，如"15元/个", "100/千粉"）

实体抽取要求（重要）：
1. 完整保留：所有账号、联系方式、域名一律输出**完整原始值**，严禁用 *** 掩码或省略，严禁脱敏。
2. 穷尽提取：宁可多抽不可漏抽，原文里每一个 @账号、微信号、QQ号、电报号、域名、邀请码都要进 entities。
3. 若某类不存在则返回空数组 []。

- summary: 一句话中文摘要，需点明所提供的服务类型与主要引流渠道（如有），不相关则为空

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
