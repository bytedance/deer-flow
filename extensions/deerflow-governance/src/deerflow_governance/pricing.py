"""模型价目表 → 金额口径（零三方依赖）。

为什么要有金额而不是只算 token：
「这次任务花了 84 万 token」对业务方没有意义，「这次任务花了 4.7 元」才有。
预算熔断要能按金额设阈值，成本归因要能按人/按线程/按子 agent 出账。

**不认识的模型返回 None，绝不返回 0。** 把未知成本当成零，会让整个预算体系
在换模型的那一天静默失效 —— 这是可观测性里最典型的伪健康状态。
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass


@dataclass(frozen=True)
class Price:
    """每百万 token 的价格，单位：分（人民币）。用分而不是元，避免浮点累加误差放大。"""

    input_cents_per_mtok: float
    output_cents_per_mtok: float
    currency: str = "CNY"


# 默认表只放几个常见模型做示例。真实价格随时会变，**上线前必须核对官方价目页**，
# 因此这里刻意不写死成「事实」，而是当作可覆盖的默认值。
DEFAULT_PRICES: dict[str, Price] = {
    "deepseek-chat": Price(200.0, 800.0),
    "deepseek-reasoner": Price(400.0, 1600.0),
    "qwen-max*": Price(2400.0, 9600.0),
    "qwen-plus*": Price(80.0, 200.0),
    "qwen3-*": Price(80.0, 200.0),
    "gpt-4o*": Price(1800.0, 7200.0),
    "claude-*sonnet*": Price(2160.0, 10800.0),
    "claude-*haiku*": Price(180.0, 900.0),
    "gemini-*flash*": Price(54.0, 216.0),
}


class PriceBook:
    def __init__(self, prices: dict[str, Price] | None = None, *, strict: bool = False) -> None:
        """strict=True 时，遇到未知模型直接抛错而不是返回 None。

        生产环境建议 strict=True：宁可启动失败，也不要跑了一个月才发现某个模型的成本一直记成 0。
        """
        self._prices = dict(prices if prices is not None else DEFAULT_PRICES)
        self._strict = strict

    def lookup(self, model: str | None) -> Price | None:
        if not model:
            return None
        if model in self._prices:
            return self._prices[model]
        # 最长匹配优先，避免 qwen3-* 抢在 qwen3-coder-plus 的精确条目前面
        candidates = [(pat, p) for pat, p in self._prices.items() if fnmatch.fnmatch(model, pat)]
        if candidates:
            return max(candidates, key=lambda kv: len(kv[0]))[1]
        if self._strict:
            raise KeyError(f"模型 {model!r} 没有价目，无法计算成本（strict 模式）")
        return None

    def cost_cents(self, model: str | None, input_tokens: int, output_tokens: int) -> float | None:
        price = self.lookup(model)
        if price is None:
            return None
        return input_tokens / 1_000_000 * price.input_cents_per_mtok + output_tokens / 1_000_000 * price.output_cents_per_mtok

    @classmethod
    def from_dict(cls, data: dict, *, strict: bool = False) -> "PriceBook":
        prices = {
            name: Price(
                input_cents_per_mtok=float(v["input_cents_per_mtok"]),
                output_cents_per_mtok=float(v["output_cents_per_mtok"]),
                currency=v.get("currency", "CNY"),
            )
            for name, v in (data or {}).items()
        }
        return cls(prices or None, strict=strict)


def format_cents(cents: float | None) -> str:
    """给人看的金额。None 显示 N/A，不显示 0.00 —— 两者含义完全不同。"""
    if cents is None:
        return "N/A"
    return f"¥{cents / 100:.4f}" if cents < 100 else f"¥{cents / 100:.2f}"
