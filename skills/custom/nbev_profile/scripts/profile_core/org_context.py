"""
org_context.py — 机构上下文解析（user_id -> org_id / org_name）

当前实现：按需求先写死 org_id="05"、org_name="深圳"。

设计要点（harness engineering）：
- 机构解析是一个"接缝（seam）"：今天写死，明天换成用户中心接口，
  调用方代码一行都不用改——只改这一个函数的函数体。
- 不在 SKILL.md 里出现任何机构字面量；机构是"由身份派生的上下文"，
  不是 LLM 需要理解或填写的业务参数。
- 写死值集中在一处常量，便于未来 grep / 替换 / 注入。
"""

from __future__ import annotations

from dataclasses import dataclass


# ── 写死的机构信息（未来替换为接口/缓存时，只动这里）──
_HARDCODED_ORG_ID = "05"
_HARDCODED_ORG_NAME = "深圳"


@dataclass(frozen=True)
class OrgContext:
    org_id: str
    org_name: str
    user_id: str


def resolve_org_context(user_id: str) -> OrgContext:
    """
    根据 user_id 返回机构上下文。

    现状：恒定返回写死的 05/深圳（user_id 仅透传，便于日志追踪）。
    未来：把函数体替换为「查用户中心 + TTL 缓存」即可，签名与返回类型保持不变。
    """
    uid = (user_id or "").strip() or "unknown"
    return OrgContext(
        org_id=_HARDCODED_ORG_ID,
        org_name=_HARDCODED_ORG_NAME,
        user_id=uid,
    )
