"""审批引擎 —— 把「策略判定 + 审批单 + 审计」串成一个可离线单测的纯逻辑核心。

provider.py 只是把 DeerFlow 的 GuardrailRequest 搬进来、把结果搬回去；
所有真正的判断都在这里，因此这一层能在不装 DeerFlow、不装 langchain 的环境里被完整覆盖。

三态语义（这是本包相对 DeerFlow 原生 guardrail 的核心增量）：

    allow → 直接放行
    deny  → 拒绝，给模型一条可读的原因，让它换路径而不是盲目重试
    ask   → **挂起等人批**。DeerFlow 原生只有 allow/deny 两态，没有这一态。

`ask` 的落地方式有两种模式：

- `ticket`（默认）：开一张审批单，本次调用先拒绝并把单号告诉模型。人批完之后，
  模型或用户重试同一个操作即放行。**不依赖 checkpointer、不依赖 resume 语义，
  子 agent 里也能用**（DeerFlow 的子 agent 图是 `checkpointer=False` 编译的，
  一次性执行、从不 resume，所以在子 agent 里 interrupt 是不成立的）。
- `interrupt`（实验）：调用 LangGraph 的 `interrupt()` 真正挂起。
  依据是 DeerFlow 的 `GuardrailMiddleware` 显式 `except GraphBubbleUp: raise`，
  注释写着 "Preserve LangGraph control-flow signals (interrupt/pause/resume)" ——
  说明 provider 层就是官方预留的 HITL 挂载点。但**上游 Gateway 的 resume 通路本人未实测**，
  故不设为默认，详见 docs/INTEGRATION.md。
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from .contracts import AuditRecord, CallContext, Effect, Ticket, TicketStatus, Verdict
from .fingerprint import brief as make_brief
from .policy import PolicyEngine
from .store import GovernanceStore


@dataclass
class Decision:
    """引擎对外的最终结论。provider 直接翻译成 GuardrailDecision，不再做判断。"""

    allow: bool
    code: str
    message: str
    verdict: Verdict
    ticket: Ticket | None = None
    needs_interrupt: bool = False  # interrupt 模式下由 provider 负责真正调用 interrupt()


_PENDING_TMPL = (
    "此操作需要人工审批，已提交审批单 {ticket_id}（风险等级：{risk}，命中规则：{rule_id}）。"
    "原因：{reason}\n"
    "在审批通过之前请不要重试本操作，也不要尝试用其他工具绕过它。"
    "你可以：先完成不需要审批的部分，或向用户说明正在等待 {ticket_id} 的审批结果。"
)
_DENIED_TMPL = (
    "此操作被治理策略拒绝（规则 {rule_id}，风险等级：{risk}）。原因：{reason}\n"
    "请换一种不触发该策略的实现方式，不要重试同一个调用。"
)
_TICKET_DENIED_TMPL = "此操作的审批单 {ticket_id} 已被人工驳回。驳回意见：{note}\n请按驳回意见调整方案，不要重试。"
_EXPIRED_TMPL = "此操作此前的审批已过期（审批单 {ticket_id}），需要重新申请。已提交新的审批单 {new_ticket_id}。"


class ApprovalEngine:
    def __init__(
        self,
        policy: PolicyEngine,
        store: GovernanceStore,
        *,
        mode: str = "ticket",
        auto_expire: bool = True,
    ) -> None:
        if mode not in {"ticket", "interrupt"}:
            raise ValueError(f"未知的审批模式: {mode}（只支持 ticket / interrupt）")
        self.policy = policy
        self.store = store
        self.mode = mode
        self.auto_expire = auto_expire

    # ------------------------------------------------------------------

    def decide(self, ctx: CallContext, *, now: float | None = None) -> Decision:
        now = now if now is not None else time.time()
        verdict = self.policy.evaluate(ctx)

        self.store.append_audit(
            AuditRecord.new(
                "policy_decision", tool_name=ctx.tool_name, effect=verdict.effect.value,
                rule_id=verdict.rule_id, risk=verdict.risk, fingerprint=verdict.fingerprint,
                thread_id=ctx.thread_id, run_id=ctx.run_id, user_id=ctx.user_id,
                is_subagent=ctx.is_subagent,
                detail={"brief": make_brief(ctx.tool_name, ctx.tool_input), "grant_scope": verdict.grant_scope},
            )
        )

        if verdict.effect is Effect.ALLOW:
            return Decision(True, "governance.allowed", verdict.reason, verdict)

        if verdict.effect is Effect.DENY:
            return Decision(
                False, "governance.denied",
                _DENIED_TMPL.format(rule_id=verdict.rule_id, risk=verdict.risk, reason=verdict.reason),
                verdict,
            )

        return self._handle_ask(ctx, verdict, now)

    # ------------------------------------------------------------------

    def _handle_ask(self, ctx: CallContext, verdict: Verdict, now: float) -> Decision:
        existing = self.store.find_by_fingerprint(verdict.fingerprint)

        if existing is not None:
            if existing.status is TicketStatus.APPROVED:
                if existing.is_valid_at(now):
                    return Decision(True, "governance.approved", f"已由 {existing.decided_by} 批准（{existing.ticket_id}）", verdict, ticket=existing)
                if self.auto_expire:
                    self.store.expire_stale(now=now)
                fresh = self._open_ticket(ctx, verdict, now)
                return Decision(
                    False, "governance.approval_expired",
                    _EXPIRED_TMPL.format(ticket_id=existing.ticket_id, new_ticket_id=fresh.ticket_id),
                    verdict, ticket=fresh, needs_interrupt=self.mode == "interrupt",
                )

            if existing.status is TicketStatus.DENIED:
                return Decision(
                    False, "governance.approval_denied",
                    _TICKET_DENIED_TMPL.format(ticket_id=existing.ticket_id, note=existing.decision_note or "（无）"),
                    verdict, ticket=existing,
                )

            if existing.status is TicketStatus.PENDING:
                # 已经在等了就不要重复开单，否则模型每重试一次就多一张单，审批队列会被刷爆
                return Decision(
                    False, "governance.approval_pending",
                    _PENDING_TMPL.format(ticket_id=existing.ticket_id, risk=verdict.risk, rule_id=verdict.rule_id, reason=verdict.reason),
                    verdict, ticket=existing, needs_interrupt=self.mode == "interrupt",
                )

        ticket = self._open_ticket(ctx, verdict, now)
        return Decision(
            False, "governance.approval_pending",
            _PENDING_TMPL.format(ticket_id=ticket.ticket_id, risk=verdict.risk, rule_id=verdict.rule_id, reason=verdict.reason),
            verdict, ticket=ticket, needs_interrupt=self.mode == "interrupt",
        )

    def _open_ticket(self, ctx: CallContext, verdict: Verdict, now: float) -> Ticket:
        ticket = Ticket.new(ctx, verdict, now=now, brief=make_brief(ctx.tool_name, ctx.tool_input))
        self.store.create_ticket(ticket)
        self.store.append_audit(
            AuditRecord.new(
                "ticket_created", tool_name=ctx.tool_name, effect="ask", rule_id=verdict.rule_id,
                risk=verdict.risk, fingerprint=verdict.fingerprint, ticket_id=ticket.ticket_id,
                thread_id=ctx.thread_id, run_id=ctx.run_id, user_id=ctx.user_id, is_subagent=ctx.is_subagent,
                detail={"brief": ticket.tool_input_brief, "expires_at": ticket.expires_at},
            )
        )
        return ticket
