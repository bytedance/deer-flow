"""跨层唯一语义真源。

刻意只用 dataclass 而不用 pydantic：本包的核心层要能在**不安装 DeerFlow、不安装 langchain**
的环境里被完整单测（见 tests/），少一个依赖就少一处版本冲突面。
适配层（provider.py / middleware.py）才允许 import langchain / langgraph。
"""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class Effect(str, Enum):
    """策略判定结果。"""

    ALLOW = "allow"
    ASK = "ask"  # 需要人工审批
    DENY = "deny"


class TicketStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"


class BudgetLevel(str, Enum):
    OK = "ok"
    WARN = "warn"
    STOP = "stop"


class Scope(str, Enum):
    """规则适用范围。DeerFlow 的 GuardrailRequest 自带 is_subagent，这里直接对齐。"""

    ANY = "any"
    LEAD = "lead"
    SUBAGENT = "subagent"


# --------------------------------------------------------------------------
# 调用上下文
# --------------------------------------------------------------------------


@dataclass
class CallContext:
    """一次工具调用的治理上下文。

    字段刻意与 DeerFlow 的 `deerflow.guardrails.provider.GuardrailRequest` 一一对齐，
    provider.py 只做字段搬运，不做语义转换 —— 上游改字段时只有一处需要跟。
    """

    tool_name: str
    tool_input: dict[str, Any] = field(default_factory=dict)
    thread_id: str | None = None
    run_id: str | None = None
    tool_call_id: str | None = None
    user_id: str | None = None
    user_role: str | None = None
    agent_id: str | None = None
    is_subagent: bool = False
    timestamp: str = ""

    @property
    def scope(self) -> Scope:
        return Scope.SUBAGENT if self.is_subagent else Scope.LEAD


# --------------------------------------------------------------------------
# 策略判定
# --------------------------------------------------------------------------


@dataclass
class Verdict:
    """策略引擎的输出。provider 只消费这个结构，不重新判断。"""

    effect: Effect
    rule_id: str
    reason: str
    risk: str = "unknown"  # low / medium / high / critical
    fingerprint: str = ""
    grant_scope: str = "exact"  # exact / tool / rule —— 批准一次能覆盖多大范围
    ttl_seconds: int = 0  # 批准的有效期，0 表示只对本次生效

    def to_dict(self) -> dict:
        d = asdict(self)
        d["effect"] = self.effect.value
        return d


# --------------------------------------------------------------------------
# 审批单
# --------------------------------------------------------------------------


@dataclass
class Ticket:
    """人工审批单。

    这是「挂起等人批」这个流程的物化：DeerFlow 原生 guardrail 只有 allow/deny 两态，
    没有第三态，本包补的就是这一态。
    """

    ticket_id: str
    fingerprint: str
    status: TicketStatus
    tool_name: str
    tool_input_brief: str
    reason: str
    rule_id: str
    risk: str
    thread_id: str | None
    run_id: str | None
    is_subagent: bool
    created_at: float
    decided_at: float | None = None
    decided_by: str | None = None
    decision_note: str = ""
    expires_at: float | None = None
    grant_scope: str = "exact"

    @classmethod
    def new(cls, ctx: CallContext, verdict: Verdict, *, now: float, brief: str) -> "Ticket":
        return cls(
            ticket_id="APR-" + uuid.uuid4().hex[:10].upper(),
            fingerprint=verdict.fingerprint,
            status=TicketStatus.PENDING,
            tool_name=ctx.tool_name,
            tool_input_brief=brief,
            reason=verdict.reason,
            rule_id=verdict.rule_id,
            risk=verdict.risk,
            thread_id=ctx.thread_id,
            run_id=ctx.run_id,
            is_subagent=ctx.is_subagent,
            created_at=now,
            expires_at=(now + verdict.ttl_seconds) if verdict.ttl_seconds else None,
            grant_scope=verdict.grant_scope,
        )

    def is_valid_at(self, now: float) -> bool:
        """已批准且未过期。过期的批准不能继续放行 —— 这是审批制度的基本要求。"""
        if self.status is not TicketStatus.APPROVED:
            return False
        return self.expires_at is None or now < self.expires_at


# --------------------------------------------------------------------------
# 预算
# --------------------------------------------------------------------------


@dataclass
class Usage:
    """一次增量用量。cost_cents 为 None 表示该模型无价目，禁止当 0 处理。"""

    input_tokens: int = 0
    output_tokens: int = 0
    tool_calls: int = 0
    delegations: int = 0
    wall_ms: int = 0
    cost_cents: float | None = None

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class BudgetVerdict:
    level: BudgetLevel
    dimension: str = ""
    used: float = 0.0
    limit: float = 0.0
    scope: str = ""
    message: str = ""

    @property
    def ratio(self) -> float:
        return (self.used / self.limit) if self.limit else 0.0


# --------------------------------------------------------------------------
# 审计
# --------------------------------------------------------------------------


@dataclass
class AuditRecord:
    """审计账本的一行。追加写，永不修改 —— 审计记录被改就没有审计价值了。"""

    record_id: str
    ts: float
    kind: str  # policy_decision / ticket_created / ticket_decided / budget_event
    tool_name: str = ""
    effect: str = ""
    rule_id: str = ""
    risk: str = ""
    fingerprint: str = ""
    ticket_id: str = ""
    thread_id: str | None = None
    run_id: str | None = None
    user_id: str | None = None
    is_subagent: bool = False
    detail: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def new(cls, kind: str, **kwargs: Any) -> "AuditRecord":
        return cls(record_id=uuid.uuid4().hex[:16], ts=time.time(), kind=kind, **kwargs)

    def to_dict(self) -> dict:
        return asdict(self)
