"""LLM-driven candidate-group reviewer.

Two-stage decision pipeline (see
docs/superpowers/specs/2026-06-06-llm-candidate-reviewer-design.md):

  Stage 1 — cheap metadata triage (batched).
  Stage 2 — expensive raw-text adjudication (one candidate at a time).

This module owns the prompts, schemas, and downgrade rules. It does NOT
write yaml or join groups — that is the CLI orchestrator's job.
"""

from __future__ import annotations

import enum
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from openai import AsyncOpenAI

logger = logging.getLogger("tg_crawler")


class Stage1Decision(enum.Enum):
    ADVANCE = "advance"
    REJECT = "reject"
    UNCERTAIN = "uncertain"


@dataclass
class Stage1Result:
    index: int
    decision: Stage1Decision
    confidence: str  # "high" | "medium" | "low"
    reason: str


@dataclass
class Stage2Result:
    decision: str           # "approve" | "reject"
    confidence: str         # "high" | "medium" | "low"
    risk_type: str
    reason: str


STAGE1_SYSTEM_PROMPT = """你是一个黑灰产情报分析专家。下面给你一批候选 Telegram 群组（candidates），\
每条候选包含：群名/邀请哈希、被提到的次数、最早/最近出现时间、被哪些来源群传播、来源群本身的历史情报\
信誉（high/medium 计数）。

判断每个候选是否值得进一步审查（是否可能是字节跳动/抖音/TikTok 相关黑灰产群）。

返回 JSON 数组（不要其他内容），每个元素：
- index: 候选编号（从0开始，与输入对应）
- decision: "advance" | "reject" | "uncertain"
  - advance: 信号明确，疑似黑灰产，进入下一阶段拿原文细看
  - reject: 明显无关（例如来源群是羊毛福利群、count 极低、群名无关键信号）
  - uncertain: 信号模糊，进入下一阶段但用更严标准
- confidence: "high" | "medium" | "low"，对你的 decision 有多确信
- reason: 一句话中文理由

只返回 JSON 数组，不要 markdown 围栏。"""


STAGE2_SYSTEM_PROMPT = """你是一个黑灰产情报分析专家。下面给你一个 Telegram 候选群组以及它在已知群里被传播\
时的来源消息原文。判断它是否值得加入字节系黑灰产监控。

返回 JSON 对象（不要其他内容）：
- decision: "approve" | "reject"
- confidence: "high" | "medium" | "low"
- risk_type: 账号交易 | 刷量作弊 | 引流诈骗 | 数据泄露 | 工具交易 | 其他（reject 时为空）
- reason: 一句话中文理由

只返回 JSON 对象。"""


class CandidateReviewer:
    def __init__(
        self,
        *,
        llm_config: dict,
        intel_stats,           # IntelStatsAggregator-like (.score_for(group))
        raw_lookup,            # RawMessageLookup-like (.get(group, msg_id)) or None
        client: AsyncOpenAI | None = None,
    ):
        self._llm_config = llm_config
        self._intel_stats = intel_stats
        self._raw_lookup = raw_lookup
        self._client = client or AsyncOpenAI(
            api_key=llm_config["api_key"],
            base_url=llm_config["base_url"],
        )
        self._model = llm_config["model"]

    # ---------- Stage 1 ----------

    def _candidate_to_stage1_dict(self, c: dict) -> dict:
        key = c["key"]
        kind = "private" if key.startswith("+") else "public"
        sources = c.get("sources") or []
        score_table = {
            s["group"]: self._intel_stats.score_for(s["group"])
            for s in sources
            if s.get("group")
        }
        return {
            "key": key,
            "type": kind,
            "count": int(c.get("count", 0)),
            "first_seen": (c.get("first_seen") or "")[:10],
            "last_seen": (c.get("last_seen") or "")[:10],
            "sources": [
                {"group": s.get("group", ""), "channel": s.get("channel", "")}
                for s in sources
            ],
            "source_groups_intel_score": score_table,
        }

    def _build_stage1_prompt(self, candidates: list[dict]) -> str:
        items = []
        for i, c in enumerate(candidates):
            items.append({"index": i, **self._candidate_to_stage1_dict(c)})
        body = json.dumps(items, ensure_ascii=False, indent=2)
        return f"请审查以下 {len(candidates)} 个候选群组：\n\n{body}"

    def _parse_stage1_response(
        self, response_text: str, expected_count: int
    ) -> list[Stage1Result]:
        text = response_text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0]
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            logger.warning("stage1 parse failed: %s", e)
            return []
        if not isinstance(data, list) or len(data) != expected_count:
            logger.warning(
                "stage1 count mismatch: got %s expected %d",
                len(data) if isinstance(data, list) else "non-list",
                expected_count,
            )
            return []
        out: list[Stage1Result] = []
        for item in data:
            try:
                idx = int(item["index"])
            except (KeyError, TypeError, ValueError):
                continue
            dec_raw = (item.get("decision") or "").lower()
            try:
                dec = Stage1Decision(dec_raw)
            except ValueError:
                dec = Stage1Decision.UNCERTAIN
            out.append(Stage1Result(
                index=idx,
                decision=dec,
                confidence=(item.get("confidence") or "").lower(),
                reason=item.get("reason") or "",
            ))
        return out

    async def stage1_review(
        self, candidates: list[dict], *, batch_size: int = 30
    ) -> list[Stage1Result]:
        """Run Stage 1 over all candidates, batching by ``batch_size``."""
        results: list[Stage1Result] = []
        for start in range(0, len(candidates), batch_size):
            batch = candidates[start:start + batch_size]
            prompt = self._build_stage1_prompt(batch)
            try:
                resp = await self._client.chat.completions.create(
                    model=self._model,
                    messages=[
                        {"role": "system", "content": STAGE1_SYSTEM_PROMPT},
                        {"role": "user",   "content": prompt},
                    ],
                    temperature=0.1,
                )
                content = resp.choices[0].message.content
            except Exception as e:
                logger.warning("stage1 LLM call failed for batch %d: %s", start, e)
                continue
            parsed = self._parse_stage1_response(content, expected_count=len(batch))
            # Re-base the local index back to the global candidate index.
            for r in parsed:
                if 0 <= r.index < len(batch):
                    r.index = start + r.index
                    results.append(r)
        return results

    _CONFIDENCE_LADDER = ("high", "medium", "low")

    def _apply_downgrades(self, confidence: str, levels: int) -> str:
        """Lower confidence by N steps along high → medium → low. Floors at low."""
        if confidence not in self._CONFIDENCE_LADDER:
            return "low"
        idx = self._CONFIDENCE_LADDER.index(confidence)
        return self._CONFIDENCE_LADDER[
            min(idx + max(levels, 0), len(self._CONFIDENCE_LADDER) - 1)
        ]

    # ---------- Stage 2 ----------

    def _build_stage2_prompt(
        self, candidate: dict, stage1: Optional[Stage1Result]
    ) -> tuple[str, int]:
        """Build Stage 2 prompt; returns (prompt_text, raw_text_found_count)."""
        key = candidate["key"]
        sources = candidate.get("sources") or []
        s1_note = (
            f"[Stage1: decision={stage1.decision.value}, confidence={stage1.confidence}, "
            f"reason={stage1.reason}]\n"
            if stage1 is not None
            else ""
        )

        lines = [s1_note + f"候选：{key}"]
        lines.append(
            f"出现 {candidate.get('count', 0)} 次, "
            f"first_seen={candidate.get('first_seen','')[:10]}, "
            f"last_seen={candidate.get('last_seen','')[:10]}"
        )
        lines.append("来源记录（最多 3 条）：")

        found = 0
        for i, s in enumerate(sources[:3]):
            grp = s.get("group", "")
            msg_id = s.get("msg_id")
            channel = s.get("channel", "")
            if self._raw_lookup is not None and msg_id is not None:
                text = self._raw_lookup.get(grp, msg_id)
            else:
                text = None
            if text:
                found += 1
                lines.append(f"[{i+1}] 群={grp}, msg_id={msg_id}, channel={channel}")
                lines.append(f'原文："{text}"')
            else:
                lines.append(
                    f"[{i+1}] 群={grp}, msg_id={msg_id}, channel={channel} — [原文未找到]"
                )

        return "\n".join(lines), found

    def _parse_stage2_response(self, response_text: str) -> Optional[Stage2Result]:
        text = response_text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0]
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            logger.warning("stage2 parse failed: %s", e)
            return None
        if not isinstance(data, dict):
            return None
        decision = (data.get("decision") or "").lower()
        if decision not in ("approve", "reject"):
            logger.warning("stage2 unknown decision: %r", decision)
            return None
        return Stage2Result(
            decision=decision,
            confidence=(data.get("confidence") or "").lower() or "low",
            risk_type=data.get("risk_type") or "",
            reason=data.get("reason") or "",
        )

    async def review_one(
        self, candidate: dict, *, stage1: Optional[Stage1Result],
    ) -> Optional[dict]:
        """Run Stage 2 (or short-circuit on Stage1 reject) and return a verdict
        block ready to hand to ``CandidatePool.set_llm_verdict``.

        Returns None on LLM failure (caller should skip writing verdict so
        increment-rereview will pick this candidate up next run).
        """
        from datetime import datetime, timezone

        now_iso = datetime.now(timezone.utc).isoformat()
        cur_count = int(candidate.get("count", 0))

        # --- Short-circuit: Stage 1 reject ---
        if stage1 is not None and stage1.decision is Stage1Decision.REJECT:
            return {
                "verdict": "llm_rejected",
                "confidence": stage1.confidence or "low",
                "risk_type": "",
                "reason": stage1.reason or "stage1 rejected",
                "reviewed_at": now_iso,
                "reviewed_count": cur_count,
                "stage": 1,
                "model": self._model,
            }

        # --- Stage 2 LLM call ---
        prompt, raw_found = self._build_stage2_prompt(candidate, stage1=stage1)
        try:
            resp = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": STAGE2_SYSTEM_PROMPT},
                    {"role": "user",   "content": prompt},
                ],
                temperature=0.1,
            )
            content = resp.choices[0].message.content
        except Exception as e:
            logger.warning("stage2 LLM call failed for %s: %s", candidate.get("key"), e)
            return None

        s2 = self._parse_stage2_response(content)
        if s2 is None:
            return None

        # --- Stage 2 reject ---
        if s2.decision == "reject":
            return {
                "verdict": "llm_rejected",
                "confidence": s2.confidence or "low",
                "risk_type": "",
                "reason": s2.reason,
                "reviewed_at": now_iso,
                "reviewed_count": cur_count,
                "stage": 2,
                "model": self._model,
            }

        # --- Stage 2 approve: apply downgrades ---
        downgrade = 0
        if stage1 is not None and stage1.decision is Stage1Decision.UNCERTAIN:
            downgrade += 1
        if candidate["key"].startswith("+"):
            downgrade += 1
        if raw_found == 0:
            downgrade += 1

        final_conf = self._apply_downgrades(s2.confidence, levels=downgrade)
        verdict_name = {
            "high":   "llm_approved_high",
            "medium": "llm_approved_medium",
            "low":    "llm_approved_low",
        }[final_conf]

        return {
            "verdict": verdict_name,
            "confidence": final_conf,
            "risk_type": s2.risk_type,
            "reason": s2.reason,
            "reviewed_at": now_iso,
            "reviewed_count": cur_count,
            "stage": 2,
            "model": self._model,
        }
