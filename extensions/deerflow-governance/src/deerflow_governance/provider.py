"""GuardrailProvider 适配层 —— 唯一接触 DeerFlow 类型的文件之一。

挂载方式（config.yaml）：

    guardrails:
      enabled: true
      fail_closed: true
      provider:
        use: "deerflow_governance.provider:ApprovalGuardrailProvider"
        config:
          config_path: "./governance.yaml"

DeerFlow 用 `resolve_variable()` 反射加载这个类路径，把 `config` 段作为 kwargs 传进构造函数
（与 models / tools / sandbox 完全同一套机制），因此**接入本包不需要改 DeerFlow 一行代码**。

本文件刻意保持很薄：字段搬运 + 结果翻译，所有判断在 engine.py，
这样 engine 能在不装 DeerFlow 的环境里被完整单测。
"""

from __future__ import annotations

import logging
from typing import Any

from .config import GovernanceConfig, load as load_config
from .contracts import CallContext
from .engine import ApprovalEngine

logger = logging.getLogger(__name__)


class ApprovalGuardrailProvider:
    """三态审批 provider：allow / deny / ask（挂起等人批）。

    DeerFlow 原生的 `GuardrailDecision` 只有 allow 布尔位，没有「待审批」这一态。
    这里把 ask 表达成 `allow=False` + 结构化 reason code `governance.approval_pending`，
    并在 reason.message 里告诉模型审批单号与「不要绕过」的明确指令 ——
    否则模型收到一个裸拒绝，会立刻尝试用别的工具达成同样的效果。
    """

    name = "deerflow-governance-approval"

    def __init__(self, *, config_path: str | None = None, config: GovernanceConfig | None = None) -> None:
        self._cfg = config or load_config(config_path)
        self._engine = ApprovalEngine(
            self._cfg.policy,
            self._cfg.build_store(),
            mode=self._cfg.approval_mode,
        )

    # ---------------- GuardrailProvider 协议 ----------------

    def evaluate(self, request: Any):  # request: deerflow.guardrails.provider.GuardrailRequest
        from deerflow.guardrails.provider import GuardrailDecision, GuardrailReason

        ctx = self._to_context(request)
        decision = self._engine.decide(ctx)

        if decision.needs_interrupt and not decision.allow:
            self._raise_interrupt(decision)

        return GuardrailDecision(
            allow=decision.allow,
            reasons=[GuardrailReason(code=decision.code, message=decision.message)],
            policy_id=decision.verdict.rule_id,
            metadata={
                "risk": decision.verdict.risk,
                "fingerprint": decision.verdict.fingerprint,
                "ticket_id": decision.ticket.ticket_id if decision.ticket else "",
                "grant_scope": decision.verdict.grant_scope,
            },
        )

    async def aevaluate(self, request: Any):
        # 判定全是本地计算 + SQLite，没有网络 IO；引入 async 只会多一层线程池而不会更快。
        # 若未来接入远程策略服务，这里再改成真正的异步实现。
        return self.evaluate(request)

    # ---------------- 内部 ----------------

    @staticmethod
    def _to_context(request: Any) -> CallContext:
        return CallContext(
            tool_name=getattr(request, "tool_name", "") or "",
            tool_input=getattr(request, "tool_input", None) or {},
            thread_id=getattr(request, "thread_id", None),
            run_id=getattr(request, "run_id", None),
            tool_call_id=getattr(request, "tool_call_id", None),
            user_id=getattr(request, "user_id", None),
            user_role=getattr(request, "user_role", None),
            agent_id=getattr(request, "agent_id", None),
            is_subagent=bool(getattr(request, "is_subagent", False)),
            timestamp=getattr(request, "timestamp", "") or "",
        )

    def _raise_interrupt(self, decision) -> None:
        """interrupt 模式：抛 LangGraph 的控制流信号真正挂起。

        DeerFlow 的 GuardrailMiddleware 里有 `except GraphBubbleUp: raise`，
        注释是 "Preserve LangGraph control-flow signals (interrupt/pause/resume)"，
        所以这个信号能干净地穿过中间件冒泡上去。

        ⚠️ 上游 Gateway 的 resume 通路本人未实测，且 DeerFlow 的子 agent 图是
        `checkpointer=False` 编译的（一次性执行、从不 resume），子 agent 里用不了这个模式。
        默认模式是 ticket，这条路径只在显式配置 approval_mode: interrupt 时才走。
        """
        from langgraph.types import interrupt

        interrupt(
            {
                "type": "governance_approval_required",
                "ticket_id": decision.ticket.ticket_id if decision.ticket else "",
                "tool_name": decision.ticket.tool_name if decision.ticket else "",
                "brief": decision.ticket.tool_input_brief if decision.ticket else "",
                "risk": decision.verdict.risk,
                "rule_id": decision.verdict.rule_id,
                "reason": decision.verdict.reason,
            }
        )
