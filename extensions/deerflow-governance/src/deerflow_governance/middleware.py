"""BudgetBreakerMiddleware —— 分层成本预算与熔断。

挂载方式（backend/packages/harness/deerflow/agents/lead_agent/agent.py 已经预留了口子）：

    build_middlewares(config, model_name, custom_middlewares=[BudgetBreakerMiddleware.from_config()])

`build_middlewares` 的第 379-380 行是 `if custom_middlewares: middlewares.extend(custom_middlewares)`，
插入位置在 safety/clarification 尾巴之前，正是自定义中间件的官方注入点。

与 DeerFlow 自带能力的边界（刻意不重复造轮子）：

| 已有 | 本中间件补的 |
|---|---|
| `TokenBudgetMiddleware`：单 run 的 token 上限 | thread / day 两层，以及 token 之外的四个维度 |
| `SubagentLimitMiddleware`：并发子 agent ≤ 3 | 委派**总次数**与子 agent 累计成本 |
| `TokenUsageMiddleware`：记录 token 指标 | 按价目表折算金额，未知模型记为 unknown 而不是 0 |
| 无 | 墙钟时长熔断（长任务真正的失控形态往往是卡住而不是 token 爆炸） |

两级阈值的必要性：只有硬停没有预警，任务会毫无征兆地断在半路；
预警走 `wrap_model_call` 注入 system-reminder，让模型自己收敛策略，
这比直接砍断保留了更多有效产出。
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, SystemMessage
from langgraph.runtime import Runtime

from .budget import BudgetLedger
from .config import GovernanceConfig, load as load_config
from .contracts import AuditRecord, BudgetLevel, Usage
from .pricing import PriceBook
from .store import GovernanceStore

logger = logging.getLogger(__name__)


class BudgetBreakerMiddleware(AgentMiddleware[AgentState]):
    """按 run / thread / day 三层、五个维度做预算记账与熔断。"""

    def __init__(
        self,
        ledger: BudgetLedger,
        prices: PriceBook,
        store: GovernanceStore | None = None,
        *,
        model_name: str | None = None,
        hard_stop: bool = True,
    ) -> None:
        super().__init__()
        self._ledger = ledger
        self._prices = prices
        self._store = store
        self._model_name = model_name
        self._hard_stop = hard_stop
        self._pending_warnings: dict[str, list[str]] = {}
        self._turn_started: dict[str, float] = {}

    @classmethod
    def from_config(cls, config_path: str | None = None, *, config: GovernanceConfig | None = None, **kwargs) -> "BudgetBreakerMiddleware":
        cfg = config or load_config(config_path)
        return cls(cfg.budget, cfg.prices, cfg.build_store(), **kwargs)

    # ---------------- 上下文提取 ----------------

    @staticmethod
    def _ids(runtime: Runtime) -> tuple[str | None, str | None]:
        context = getattr(runtime, "context", None)
        context = context if isinstance(context, dict) else {}
        return context.get("run_id"), context.get("thread_id")

    def _key(self, runtime: Runtime) -> str:
        run_id, thread_id = self._ids(runtime)
        return run_id or thread_id or "default"

    # ---------------- 记账 ----------------

    @staticmethod
    def _last_ai_message(state: AgentState) -> AIMessage | None:
        for message in reversed(state.get("messages", []) or []):
            if isinstance(message, AIMessage):
                return message
        return None

    def _collect(self, state: AgentState, runtime: Runtime) -> Usage:
        message = self._last_ai_message(state)
        if message is None:
            return Usage()

        raw = getattr(message, "usage_metadata", None) or {}
        input_tokens = int(raw.get("input_tokens", 0) or 0)
        output_tokens = int(raw.get("output_tokens", 0) or 0)

        tool_calls = list(getattr(message, "tool_calls", None) or [])
        delegations = sum(1 for tc in tool_calls if (tc.get("name") if isinstance(tc, dict) else None) == "task")

        # 真实模型名优先取本次响应的 metadata，取不到才回落到构造时的模型名 ——
        # 子 agent 可能跑在不同模型上，用 lead 的模型名折算成本会系统性算错。
        metadata = getattr(message, "response_metadata", None) or {}
        model = metadata.get("model_name") or metadata.get("model") or self._model_name

        key = self._key(runtime)
        started = self._turn_started.pop(key, None)
        wall_ms = int((time.perf_counter() - started) * 1000) if started else 0

        return Usage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            tool_calls=len(tool_calls),
            delegations=delegations,
            wall_ms=wall_ms,
            cost_cents=self._prices.cost_cents(model, input_tokens, output_tokens),
        )

    # ---------------- 钩子 ----------------

    def after_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        run_id, thread_id = self._ids(runtime)
        usage = self._collect(state, runtime)
        if usage.total_tokens or usage.tool_calls or usage.wall_ms:
            self._ledger.record(usage, run_id=run_id, thread_id=thread_id)

        verdict = self._ledger.check(run_id=run_id, thread_id=thread_id)
        if verdict.level is BudgetLevel.OK:
            return None

        self._audit(verdict, run_id=run_id, thread_id=thread_id)

        if verdict.level is BudgetLevel.WARN:
            # 预警不改状态，只排队等下次 model call 时作为 system-reminder 注入
            self._pending_warnings.setdefault(self._key(runtime), []).append(verdict.message)
            return None

        if not self._hard_stop:
            self._pending_warnings.setdefault(self._key(runtime), []).append(verdict.message)
            return None

        return self._build_hard_stop(state, verdict.message)

    async def aafter_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        return self.after_model(state, runtime)

    def wrap_model_call(self, request: Any, handler: Callable[[Any], Any]) -> Any:
        self._before_call(request)
        return handler(self._inject_warnings(request))

    async def awrap_model_call(self, request: Any, handler: Callable[[Any], Awaitable[Any]]) -> Any:
        self._before_call(request)
        return await handler(self._inject_warnings(request))

    # ---------------- 内部 ----------------

    def _before_call(self, request: Any) -> None:
        runtime = getattr(request, "runtime", None)
        if runtime is not None:
            self._turn_started[self._key(runtime)] = time.perf_counter()

    def _inject_warnings(self, request: Any) -> Any:
        runtime = getattr(request, "runtime", None)
        if runtime is None:
            return request
        warnings = self._pending_warnings.pop(self._key(runtime), [])
        if not warnings:
            return request
        messages = list(getattr(request, "messages", []) or [])
        messages.append(SystemMessage(content="\n".join(f"<system-reminder>{w}</system-reminder>" for w in warnings)))
        try:
            return request.override(messages=messages)
        except AttributeError:
            # 不同 langchain 版本的 ModelRequest 可能没有 override()，降级为原地替换
            request.messages = messages
            return request

    @staticmethod
    def _build_hard_stop(state: AgentState, message: str) -> dict:
        """硬停：清空未执行的 tool_calls 并把熔断说明附到消息尾部。

        与 DeerFlow 自带 `TokenBudgetMiddleware` 的硬停做法保持一致 ——
        不抛异常中断整个 run，而是让模型基于已有信息给出一个收尾答案。
        对长任务来说，「半成品 + 明确说明还差什么」远比「一个异常堆栈」有用。
        """
        last = None
        for m in reversed(state.get("messages", []) or []):
            if isinstance(m, AIMessage):
                last = m
                break
        if last is None:
            return {}
        content = last.content
        text = content if isinstance(content, str) else str(content)
        patched = AIMessage(
            content=f"{text}\n\n{message}".strip(),
            id=last.id,
            additional_kwargs=dict(getattr(last, "additional_kwargs", {}) or {}),
            response_metadata=dict(getattr(last, "response_metadata", {}) or {}),
            tool_calls=[],
        )
        return {"messages": [patched]}

    def _audit(self, verdict, *, run_id: str | None, thread_id: str | None) -> None:
        if self._store is None:
            return
        self._store.append_audit(
            AuditRecord.new(
                "budget_event", effect=verdict.level.value, risk=verdict.dimension,
                thread_id=thread_id, run_id=run_id,
                detail={"scope": verdict.scope, "dimension": verdict.dimension, "used": verdict.used, "limit": verdict.limit},
            )
        )
