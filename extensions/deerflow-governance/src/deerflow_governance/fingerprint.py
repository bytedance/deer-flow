"""工具调用指纹。

要解决的问题：审批不能每次都问。人工批过一次 `bash: pytest tests/ -q` 之后，
同一个线程里再跑一次同样的命令还要弹审批，审批就会被当成噪音、被无脑放行 ——
这是所有审批系统失效的第一原因。

所以需要一个「同类调用」的判定：
- `exact`：参数完全一致才算同一类（最严，默认给 critical 风险用）
- `rule`：命中同一条策略规则就算同一类（最宽，给低风险批量操作用）
- `tool`：同一个工具就算同一类（中间档）

指纹必须**可复现**：同样的调用在任何机器上算出同一个值，否则审批记录跨进程失效。
因此排序 key、剔除易变字段、截断超长值，全部走同一套规范化。
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

# 这些字段每次调用都不同，不该进入指纹，否则「批过的操作」永远命中不了
VOLATILE_KEYS = {
    "tool_call_id", "run_id", "request_id", "timestamp", "trace_id",
    "sandbox_id", "session_id", "nonce", "idempotency_key",
}

_MAX_VALUE_CHARS = 400
_WS_RE = re.compile(r"\s+")


def normalize_value(value: Any, *, depth: int = 0) -> Any:
    """递归规范化参数值。

    - 字符串压缩空白并截断（超长的 write_file content 不该让指纹随一个空格变化）
    - dict 按 key 排序
    - 嵌套深度超过 4 层折叠成类型标记，防止病态输入把指纹计算拖垮
    """
    if depth > 4:
        return f"<depth-capped:{type(value).__name__}>"
    if isinstance(value, str):
        s = _WS_RE.sub(" ", value).strip()
        return s if len(s) <= _MAX_VALUE_CHARS else s[:_MAX_VALUE_CHARS] + f"…<{len(s)}chars>"
    if isinstance(value, dict):
        return {k: normalize_value(v, depth=depth + 1) for k, v in sorted(value.items()) if k not in VOLATILE_KEYS}
    if isinstance(value, (list, tuple)):
        return [normalize_value(v, depth=depth + 1) for v in value]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return f"<{type(value).__name__}>"


def canonical_args(tool_input: dict[str, Any]) -> str:
    normalized = normalize_value(dict(tool_input or {}))
    return json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def compute(
    *,
    tool_name: str,
    tool_input: dict[str, Any],
    rule_id: str,
    scope: str = "exact",
    thread_id: str | None = None,
    thread_bound: bool = True,
) -> str:
    """计算指纹。

    Args:
        scope: exact / tool / rule —— 决定指纹里包含多少信息，信息越少覆盖面越大。
        thread_bound: 批准是否只在本线程有效。默认 True：
            在 A 会话批准的 `rm -rf build/` 不应该自动放行 B 会话的同一条命令。
    """
    parts: list[str] = [f"scope={scope}"]
    if thread_bound:
        parts.append(f"thread={thread_id or '-'}")

    if scope == "rule":
        parts.append(f"rule={rule_id}")
    elif scope == "tool":
        parts.append(f"tool={tool_name}")
    elif scope == "exact":
        parts.append(f"tool={tool_name}")
        parts.append(f"args={canonical_args(tool_input)}")
    else:
        raise ValueError(f"未知的 grant scope: {scope}（只支持 exact / tool / rule）")

    raw = "|".join(parts)
    return "fp_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def brief(tool_name: str, tool_input: dict[str, Any], *, limit: int = 180) -> str:
    """给人看的一行摘要，用于审批单列表。不参与指纹计算。"""
    if not tool_input:
        return tool_name
    # bash 类工具最重要的信息就是命令本身，优先展示
    for key in ("command", "cmd", "file_path", "path", "url", "query", "description"):
        if key in tool_input and isinstance(tool_input[key], str):
            text = _WS_RE.sub(" ", tool_input[key]).strip()
            out = f"{tool_name}: {text}"
            return out if len(out) <= limit else out[: limit - 1] + "…"
    out = f"{tool_name}: {canonical_args(tool_input)}"
    return out if len(out) <= limit else out[: limit - 1] + "…"
