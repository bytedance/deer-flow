"""策略引擎（零三方依赖核心）。

设计要点：

1. **首条命中即返回**，规则有序。这是防火墙、IAM、审批系统的通用语义，
   运维人员不需要学一套新的求值模型就能读懂 governance.yaml。

2. **默认拒绝还是默认放行，必须显式写在配置里**。不给隐式默认值，
   因为「忘了配」和「故意配成放行」在审计上是两件事。

3. **参数级匹配**，而不只是工具名级。`bash: pytest -q` 和 `bash: rm -rf /`
   是同一个工具，风险差着两个数量级；只按工具名做策略，要么全放要么全拦，
   两种都会让审批失去意义。

4. **规则可解释**：每条判定都带 rule_id 和人话 reason，直接进审计账本和给模型的错误消息。
   agent 收到「被拒了」还必须知道「为什么、能不能换个方式」，否则它会盲目重试。
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from typing import Any

from .contracts import CallContext, Effect, Scope, Verdict
from .fingerprint import compute as compute_fingerprint

RISK_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


# --------------------------------------------------------------------------
# 参数条件
# --------------------------------------------------------------------------


@dataclass
class ArgCondition:
    """单个参数上的判定条件。全部条件为 AND 关系。"""

    arg: str
    equals: Any = None
    contains: str | None = None
    regex: str | None = None
    path_prefix: str | None = None
    absent: bool = False

    def __post_init__(self) -> None:
        self._compiled: re.Pattern | None = re.compile(self.regex) if self.regex else None

    def matches(self, tool_input: dict[str, Any]) -> bool:
        present = self.arg in tool_input
        if self.absent:
            return not present
        if not present:
            return False
        value = tool_input[self.arg]
        text = value if isinstance(value, str) else str(value)

        if self.equals is not None and value != self.equals:
            return False
        if self.contains is not None and self.contains not in text:
            return False
        if self._compiled is not None and not self._compiled.search(text):
            return False
        if self.path_prefix is not None and not text.replace("\\", "/").lstrip("./").startswith(self.path_prefix.lstrip("./")):
            return False
        return True

    @classmethod
    def from_dict(cls, d: dict) -> "ArgCondition":
        known = {"arg", "equals", "contains", "regex", "path_prefix", "absent"}
        unknown = set(d) - known
        if unknown:
            raise ValueError(f"未知的参数条件字段: {sorted(unknown)}；支持 {sorted(known)}")
        if "arg" not in d:
            raise ValueError("参数条件必须有 arg 字段")
        return cls(**d)


# --------------------------------------------------------------------------
# 规则
# --------------------------------------------------------------------------


@dataclass
class Rule:
    id: str
    effect: Effect
    tools: list[str] = field(default_factory=lambda: ["*"])  # 支持 glob，如 mcp__*
    scope: Scope = Scope.ANY
    risk: str = "medium"
    reason: str = ""
    when: list[ArgCondition] = field(default_factory=list)
    when_any: list[ArgCondition] = field(default_factory=list)  # OR 关系，用于「危险命令黑名单」
    grant_scope: str = "exact"
    ttl_seconds: int = 0
    roles: list[str] = field(default_factory=list)  # 为空表示不限角色

    def matches(self, ctx: CallContext) -> bool:
        if not any(fnmatch.fnmatch(ctx.tool_name, pattern) for pattern in self.tools):
            return False
        if self.scope is not Scope.ANY and self.scope is not ctx.scope:
            return False
        if self.roles and (ctx.user_role or "") not in self.roles:
            return False
        if self.when and not all(c.matches(ctx.tool_input) for c in self.when):
            return False
        if self.when_any and not any(c.matches(ctx.tool_input) for c in self.when_any):
            return False
        return True

    @classmethod
    def from_dict(cls, d: dict) -> "Rule":
        d = dict(d)
        if "id" not in d:
            raise ValueError("规则必须有 id —— 没有 id 的规则无法在审计里追溯")
        try:
            effect = Effect(d.pop("effect"))
        except KeyError as exc:
            raise ValueError(f"规则 {d.get('id')} 缺少 effect") from exc
        except ValueError as exc:
            raise ValueError(f"规则 {d.get('id')} 的 effect 非法，只能是 allow/ask/deny") from exc

        scope = Scope(d.pop("scope", "any"))
        risk = d.pop("risk", "medium")
        if risk not in RISK_ORDER:
            raise ValueError(f"规则 {d['id']} 的 risk 非法：{risk}，只能是 {sorted(RISK_ORDER)}")
        when = [ArgCondition.from_dict(c) for c in d.pop("when", [])]
        when_any = [ArgCondition.from_dict(c) for c in d.pop("when_any", [])]
        grant_scope = d.pop("grant_scope", "exact")
        if grant_scope not in {"exact", "tool", "rule"}:
            raise ValueError(f"规则 {d['id']} 的 grant_scope 非法：{grant_scope}")

        rule_id = d.pop("id")
        tools = d.pop("tools", ["*"])
        reason = d.pop("reason", "")
        ttl = int(d.pop("ttl_seconds", 0))
        roles = d.pop("roles", [])
        if d:
            raise ValueError(f"规则 {rule_id} 含未知字段: {sorted(d)}")
        return cls(
            id=rule_id, effect=effect, tools=tools, scope=scope, risk=risk, reason=reason,
            when=when, when_any=when_any, grant_scope=grant_scope, ttl_seconds=ttl, roles=roles,
        )


# --------------------------------------------------------------------------
# 引擎
# --------------------------------------------------------------------------


@dataclass
class PolicyEngine:
    rules: list[Rule]
    default_effect: Effect
    default_reason: str = "未命中任何规则，按默认策略处理"
    thread_bound_grants: bool = True

    def evaluate(self, ctx: CallContext) -> Verdict:
        for rule in self.rules:
            if rule.matches(ctx):
                fp = compute_fingerprint(
                    tool_name=ctx.tool_name,
                    tool_input=ctx.tool_input,
                    rule_id=rule.id,
                    scope=rule.grant_scope,
                    thread_id=ctx.thread_id,
                    thread_bound=self.thread_bound_grants,
                )
                return Verdict(
                    effect=rule.effect,
                    rule_id=rule.id,
                    reason=rule.reason or f"命中规则 {rule.id}",
                    risk=rule.risk,
                    fingerprint=fp,
                    grant_scope=rule.grant_scope,
                    ttl_seconds=rule.ttl_seconds,
                )

        fp = compute_fingerprint(
            tool_name=ctx.tool_name, tool_input=ctx.tool_input, rule_id="__default__",
            scope="exact", thread_id=ctx.thread_id, thread_bound=self.thread_bound_grants,
        )
        return Verdict(
            effect=self.default_effect, rule_id="__default__", reason=self.default_reason,
            risk="medium", fingerprint=fp, grant_scope="exact",
        )

    # ---------------- 加载 ----------------

    @classmethod
    def from_dict(cls, data: dict) -> "PolicyEngine":
        if "default_effect" not in data:
            raise ValueError("governance 配置必须显式声明 default_effect —— 「忘了配」和「故意放行」在审计上不是一回事")
        default = Effect(data["default_effect"])
        rules = [Rule.from_dict(r) for r in data.get("rules", [])]
        ids = [r.id for r in rules]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise ValueError(f"规则 id 重复: {sorted(dupes)} —— 重复 id 会让审计无法定位是哪一条生效")
        return cls(
            rules=rules,
            default_effect=default,
            default_reason=data.get("default_reason", "未命中任何规则，按默认策略处理"),
            thread_bound_grants=bool(data.get("thread_bound_grants", True)),
        )

    @classmethod
    def from_yaml(cls, path: str) -> "PolicyEngine":
        import yaml  # 只有加载配置时才需要，核心求值不依赖

        with open(path, encoding="utf-8") as f:
            return cls.from_dict(yaml.safe_load(f) or {})

    def explain(self, ctx: CallContext) -> list[tuple[str, bool]]:
        """调试用：返回每条规则是否命中。定位「为什么这条被放行了」时非常有用。"""
        return [(r.id, r.matches(ctx)) for r in self.rules]
