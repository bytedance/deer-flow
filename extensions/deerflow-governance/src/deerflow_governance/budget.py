"""分层预算账本与熔断判定（零三方依赖核心）。

DeerFlow 自带 `TokenBudgetMiddleware`（单 run 的 token 上限）和
`SubagentLimitMiddleware`（并发子 agent ≤ 3），本模块补的是它们没覆盖的三件事：

1. **多维度**：不只 token，还有工具调用次数、委派次数、墙钟时长、金额。
   长任务失控最常见的形态不是 token 爆炸，而是「一个子 agent 卡在某个网页上重试了 40 分钟」。
2. **多层级**：run / thread / day 三层独立计数。单 run 不超标不代表一个会话里
   连着开二十个 run 不超标，更不代表一天不超标。
3. **两级阈值**：先 warn（把剩余预算作为 system-reminder 注入，让模型自己收敛），
   再 stop（硬停）。只有硬停没有预警，会让任务在毫无征兆的情况下断在半路。

设计取舍：**账本在内存里，进程重启即清零**（除非注入持久化后端）。
理由是熔断要在工具调用的热路径上做判断，每次都读 SQLite 会把延迟带进主循环；
跨进程的日配额通过可选的 `PersistentCounterBackend` 落 SQLite，按需开启。
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Protocol

from .contracts import BudgetLevel, BudgetVerdict, Usage

DIMENSIONS = ("total_tokens", "cost_cents", "tool_calls", "delegations", "wall_ms")
LEVELS = ("run", "thread", "day")
# 严重度排序。写成显式表而不是靠枚举比较：早期版本用 `is not STOP` 做判断，
# 结果 WARN 永远压不过初始的 OK，预警一次都没触发过 —— 被 test_ok_then_warn_then_stop 抓出来。
SEVERITY = {BudgetLevel.OK: 0, BudgetLevel.WARN: 1, BudgetLevel.STOP: 2}


@dataclass
class Limits:
    """某一层级的上限。None 表示该维度不设限。"""

    total_tokens: int | None = None
    cost_cents: float | None = None
    tool_calls: int | None = None
    delegations: int | None = None
    wall_ms: int | None = None
    warn_ratio: float = 0.8

    def limit_for(self, dimension: str) -> float | None:
        value = getattr(self, dimension, None)
        return float(value) if value is not None else None

    @classmethod
    def from_dict(cls, d: dict) -> "Limits":
        known = {f for f in DIMENSIONS} | {"warn_ratio"}
        unknown = set(d or {}) - known
        if unknown:
            raise ValueError(f"未知的预算维度: {sorted(unknown)}；支持 {sorted(known)}")
        return cls(**(d or {}))


@dataclass
class Counter:
    total_tokens: int = 0
    cost_cents: float = 0.0
    tool_calls: int = 0
    delegations: int = 0
    wall_ms: int = 0
    cost_unknown_tokens: int = 0  # 无价目模型消耗的 token，单独计，不混进 cost
    started_at: float = field(default_factory=time.time)

    def add(self, usage: Usage) -> None:
        self.total_tokens += usage.total_tokens
        self.tool_calls += usage.tool_calls
        self.delegations += usage.delegations
        self.wall_ms += usage.wall_ms
        if usage.cost_cents is None:
            self.cost_unknown_tokens += usage.total_tokens
        else:
            self.cost_cents += usage.cost_cents

    def value_of(self, dimension: str) -> float:
        return float(getattr(self, dimension))

    def snapshot(self) -> dict:
        return {
            "total_tokens": self.total_tokens,
            "cost_cents": round(self.cost_cents, 4),
            "cost_unknown_tokens": self.cost_unknown_tokens,
            "tool_calls": self.tool_calls,
            "delegations": self.delegations,
            "wall_ms": self.wall_ms,
        }


class CounterBackend(Protocol):
    """可选的跨进程计数后端（用于日配额）。默认实现是纯内存。"""

    def bump(self, key: str, usage: Usage) -> Counter: ...

    def get(self, key: str) -> Counter: ...


class _BoundedCounters(OrderedDict):
    """限长 LRU。长期运行的服务里 thread/run 的 key 是无界增长的，必须封顶。"""

    def __init__(self, maxsize: int = 2000) -> None:
        super().__init__()
        self._maxsize = maxsize

    def __setitem__(self, key, value) -> None:  # type: ignore[no-untyped-def]
        super().__setitem__(key, value)
        super().move_to_end(key)
        while len(self) > self._maxsize:
            super().popitem(last=False)


class BudgetLedger:
    """线程安全的分层账本。"""

    def __init__(self, limits: dict[str, Limits], *, maxsize: int = 2000, day_backend: CounterBackend | None = None) -> None:
        unknown = set(limits) - set(LEVELS)
        if unknown:
            raise ValueError(f"未知的预算层级: {sorted(unknown)}；支持 {sorted(LEVELS)}")
        self._limits = limits
        self._counters: dict[str, _BoundedCounters] = {level: _BoundedCounters(maxsize) for level in LEVELS}
        self._day_backend = day_backend
        self._lock = threading.RLock()

    # ---------------- 记账 ----------------

    @staticmethod
    def _day_key(now: float) -> str:
        return time.strftime("%Y-%m-%d", time.gmtime(now))

    def record(self, usage: Usage, *, run_id: str | None, thread_id: str | None, now: float | None = None) -> None:
        now = now if now is not None else time.time()
        with self._lock:
            for level, key in (("run", run_id), ("thread", thread_id), ("day", self._day_key(now))):
                if key is None:
                    continue
                if level == "day" and self._day_backend is not None:
                    self._day_backend.bump(key, usage)
                    continue
                bucket = self._counters[level]
                counter = bucket.get(key)
                if counter is None:
                    counter = Counter(started_at=now)
                    bucket[key] = counter
                counter.add(usage)

    def counter(self, level: str, key: str | None) -> Counter:
        if key is None:
            return Counter()
        if level == "day" and self._day_backend is not None:
            return self._day_backend.get(key)
        with self._lock:
            return self._counters[level].get(key) or Counter()

    def reset(self, level: str, key: str) -> None:
        with self._lock:
            self._counters[level].pop(key, None)

    # ---------------- 判定 ----------------

    def check(self, *, run_id: str | None, thread_id: str | None, now: float | None = None) -> BudgetVerdict:
        """返回最严重的一条判定。stop 优先于 warn；同级取超出比例最高的维度。"""
        now = now if now is not None else time.time()
        worst = BudgetVerdict(level=BudgetLevel.OK)
        worst_ratio = 0.0

        for level, key in (("run", run_id), ("thread", thread_id), ("day", self._day_key(now))):
            limits = self._limits.get(level)
            if limits is None or key is None:
                continue
            counter = self.counter(level, key)
            for dim in DIMENSIONS:
                limit = limits.limit_for(dim)
                if not limit:
                    continue
                used = counter.value_of(dim)
                ratio = used / limit
                if ratio >= 1.0:
                    verdict_level = BudgetLevel.STOP
                elif ratio >= limits.warn_ratio:
                    verdict_level = BudgetLevel.WARN
                else:
                    continue
                # 更严重的等级永远压过较轻的；同级比超出比例
                more_severe = SEVERITY[verdict_level] > SEVERITY[worst.level]
                if more_severe or (verdict_level is worst.level and ratio > worst_ratio):
                    worst_ratio = ratio
                    worst = BudgetVerdict(
                        level=verdict_level, dimension=dim, used=used, limit=limit, scope=level,
                        message=_message(verdict_level, level, dim, used, limit),
                    )
        return worst

    def snapshot(self, *, run_id: str | None, thread_id: str | None, now: float | None = None) -> dict:
        now = now if now is not None else time.time()
        return {
            "run": self.counter("run", run_id).snapshot(),
            "thread": self.counter("thread", thread_id).snapshot(),
            "day": self.counter("day", self._day_key(now)).snapshot(),
        }

    @classmethod
    def from_dict(cls, data: dict, **kwargs) -> "BudgetLedger":
        return cls({level: Limits.from_dict(cfg) for level, cfg in (data or {}).items()}, **kwargs)


_DIM_LABEL = {
    "total_tokens": "token 用量", "cost_cents": "成本", "tool_calls": "工具调用次数",
    "delegations": "子 Agent 委派次数", "wall_ms": "执行时长",
}
_LEVEL_LABEL = {"run": "本次运行", "thread": "本会话", "day": "今日"}


def _fmt(dim: str, value: float) -> str:
    if dim == "cost_cents":
        return f"¥{value / 100:.2f}"
    if dim == "wall_ms":
        return f"{value / 1000:.0f}s"
    return f"{int(value)}"


def _message(level: BudgetLevel, scope: str, dim: str, used: float, limit: float) -> str:
    scope_label = _LEVEL_LABEL.get(scope, scope)
    dim_label = _DIM_LABEL.get(dim, dim)
    if level is BudgetLevel.STOP:
        return f"[预算熔断] {scope_label}的{dim_label}已达上限（{_fmt(dim, used)} / {_fmt(dim, limit)}），本轮停止继续调用工具。请直接给出当前已取得的结论，并说明还差哪些步骤。"
    return f"[预算预警] {scope_label}的{dim_label}已用 {_fmt(dim, used)} / {_fmt(dim, limit)}（{used / limit:.0%}）。请收敛策略：优先完成主线，避免展开次要分支。"
