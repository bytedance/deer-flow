"""沙箱审计中间件 - bash命令安全审计

===================
设计思路说明
===================

**核心职责**：
为每个bash工具调用执行安全审计：
1. **命令分类**：使用正则表达式和shlex分析将命令分级为
   高风险（阻止）、中风险（警告）或安全（通过）
2. **审计日志**：每次bash调用记录为结构化JSON条目，
   通过标准日志记录器记录（在langgraph.log中可见）

**为什么需要这个中间件**：
1. **安全防护**：防止代理执行危险命令破坏系统
2. **审计追踪**：记录所有命令执行，便于事后审查
3. **风险提示**：对中风险命令给出警告，让代理 aware
4. **优雅降级**：阻止命令时返回错误消息，允许代理继续

**设计决策**：
- **分级响应**：高风险阻止，中风险警告，低风险通过
- **模式匹配**：使用正则表达式检测危险命令模式
- **结构化日志**：JSON格式便于解析和分析
- **同步/异步**：同时支持同步和异步执行路径

**为什么只审计bash命令**：
- bash是最强大的工具，也是最危险的
- 其他工具（如read_file）相对安全
- 聚焦于最高风险的攻击面

**架构说明**：
- 在wrap_tool_call钩子中检查：工具调用前拦截
- 使用正则表达式匹配：快速识别危险模式
- 返回ToolMessage：优雅地报告错误
"""

import json
import logging
import re
import shlex
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import override

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from deerflow.agents.thread_state import ThreadState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 命令分类规则
# ---------------------------------------------------------------------------

# 为什么在导入时预编译正则表达式：
# - 性能优化：避免重复编译
# - 错误检查：启动时验证模式有效性
# - 全局复用：所有实例共享编译后的模式

# 高风险命令模式：匹配这些模式将被阻止
# 为什么这些是高风险：
# - rm -rf /: 删除系统文件，破坏性极强
# - curl|sh: 下载并执行脚本，可能执行恶意代码
# - dd: 直接写磁盘，可能破坏文件系统
# - mkfs: 格式化文件系统，会删除所有数据
# - cat /etc/shadow: 读取敏感密码文件
# Each pattern is compiled once at import time.
_HIGH_RISK_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"rm\s+-[^\s]*r[^\s]*\s+(/\*?|~/?\*?|/home\b|/root\b)\s*$"),  # rm -rf / /* ~ /home /root
    re.compile(r"(curl|wget).+\|\s*(ba)?sh"),  # curl|sh, wget|sh
    re.compile(r"dd\s+if="),
    re.compile(r"mkfs"),
    re.compile(r"cat\s+/etc/shadow"),
    re.compile(r">\s+/etc/"),  # overwrite /etc/ files
]

# 中风险命令模式：匹配这些模式将触发警告
# 为什么这些是中风险而非高风险：
# - chmod 777: 权限过宽但可逆
# - pip install: 修改环境但非破坏性
# - apt install: 安装软件但需要权限
_MEDIUM_RISK_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"chmod\s+777"),  # overly permissive, but reversible
    re.compile(r"pip\s+install"),
    re.compile(r"pip3\s+install"),
    re.compile(r"apt(-get)?\s+install"),
]


def _classify_command(command: str) -> str:
    """返回'block'、'warn'或'pass'

    **为什么需要分类函数**：
    - **标准化评估**：统一的风险评估标准
    - **可扩展性**：便于添加新的检测规则
    - **性能优化**：先高风险再中风险，快速失败

    **检测策略**：
    1. 规范化命令（压缩空白）
    2. 匹配高风险模式
    3. 尝试shlex解析后再匹配（更精确）
    4. 匹配中风险模式
    5. 默认通过

    **为什么使用两种匹配方式**：
    - 正则匹配：快速但可能有误报
    - shlex解析：更精确但可能失败
    - 结合使用：兼顾速度和准确性

    **返回值**：
        'block': 高风险，阻止执行
        'warn': 中风险，记录警告
        'pass': 低风险，正常执行
    """
    # Normalize for matching (collapse whitespace)
    normalized = " ".join(command.split())

    for pattern in _HIGH_RISK_PATTERNS:
        if pattern.search(normalized):
            return "block"

    # Also try shlex-parsed tokens for high-risk detection
    try:
        tokens = shlex.split(command)
        joined = " ".join(tokens)
        for pattern in _HIGH_RISK_PATTERNS:
            if pattern.search(joined):
                return "block"
    except ValueError:
        # shlex.split fails on unclosed quotes — treat as suspicious
        return "block"

    for pattern in _MEDIUM_RISK_PATTERNS:
        if pattern.search(normalized):
            return "warn"

    return "pass"


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


class SandboxAuditMiddleware(AgentMiddleware[ThreadState]):
    """Bash命令安全审计中间件

    **为什么需要这个中间件**：
    - **安全第一**：防止代理执行危险命令
    - **审计追踪**：记录所有命令执行
    - **风险提示**：让代理 aware 中风险操作

    **工作流程**：
    对于每个``bash``工具调用：
    1. **命令分类**：正则表达式+shlex分析将命令分级为
       高风险（阻止）、中风险（警告）或安全（通过）
    2. **审计日志**：每次bash调用记录为结构化JSON条目
       通过标准日志记录器（在langgraph.log中可见）

    **分级响应**：
    - **高风险命令**（如``rm -rf /``、``curl url | bash``）被阻止：
      不调用处理程序，返回错误``ToolMessage``，使代理循环可以优雅地继续

    - **中风险命令**（如``pip install``、``chmod 777``）正常执行：
      警告附加到工具结果，让LLM aware

    **为什么这样设计**：
    - **预防为主**：阻止而非修复
    - **透明审计**：所有命令都有记录
    - **教育意义**：警告帮助代理学习安全实践
    """

    state_schema = ThreadState

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_thread_id(self, request: ToolCallRequest) -> str | None:
        runtime = request.runtime  # ToolRuntime; may be None-like in tests
        if runtime is None:
            return None
        ctx = getattr(runtime, "context", None) or {}
        thread_id = ctx.get("thread_id") if isinstance(ctx, dict) else None
        if thread_id is None:
            cfg = getattr(runtime, "config", None) or {}
            thread_id = cfg.get("configurable", {}).get("thread_id")
        return thread_id

    def _write_audit(self, thread_id: str | None, command: str, verdict: str) -> None:
        record = {
            "timestamp": datetime.now(UTC).isoformat(),
            "thread_id": thread_id or "unknown",
            "command": command,
            "verdict": verdict,
        }
        logger.info("[SandboxAudit] %s", json.dumps(record, ensure_ascii=False))

    def _build_block_message(self, request: ToolCallRequest, reason: str) -> ToolMessage:
        tool_call_id = str(request.tool_call.get("id") or "missing_id")
        return ToolMessage(
            content=f"Command blocked: {reason}. Please use a safer alternative approach.",
            tool_call_id=tool_call_id,
            name="bash",
            status="error",
        )

    def _append_warn_to_result(self, result: ToolMessage | Command, command: str) -> ToolMessage | Command:
        """Append a warning note to the tool result for medium-risk commands."""
        if not isinstance(result, ToolMessage):
            return result
        warning = f"\n\n⚠️ Warning: `{command}` is a medium-risk command that may modify the runtime environment."
        if isinstance(result.content, list):
            new_content = list(result.content) + [{"type": "text", "text": warning}]
        else:
            new_content = str(result.content) + warning
        return ToolMessage(
            content=new_content,
            tool_call_id=result.tool_call_id,
            name=result.name,
            status=result.status,
        )

    # ------------------------------------------------------------------
    # Core logic (shared between sync and async paths)
    # ------------------------------------------------------------------

    def _pre_process(self, request: ToolCallRequest) -> tuple[str, str | None, str]:
        """
        Returns (command, thread_id, verdict).
        verdict is 'block', 'warn', or 'pass'.
        """
        args = request.tool_call.get("args", {})
        command: str = args.get("command", "")
        thread_id = self._get_thread_id(request)

        # ① classify command
        verdict = _classify_command(command)

        # ② audit log
        self._write_audit(thread_id, command, verdict)

        if verdict == "block":
            logger.warning("[SandboxAudit] BLOCKED thread=%s cmd=%r", thread_id, command)
        elif verdict == "warn":
            logger.warning("[SandboxAudit] WARN (medium-risk) thread=%s cmd=%r", thread_id, command)

        return command, thread_id, verdict

    # ------------------------------------------------------------------
    # wrap_tool_call hooks
    # ------------------------------------------------------------------

    @override
    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        if request.tool_call.get("name") != "bash":
            return handler(request)

        command, _, verdict = self._pre_process(request)
        if verdict == "block":
            return self._build_block_message(request, "security violation detected")
        result = handler(request)
        if verdict == "warn":
            result = self._append_warn_to_result(result, command)
        return result

    @override
    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        if request.tool_call.get("name") != "bash":
            return await handler(request)

        command, _, verdict = self._pre_process(request)
        if verdict == "block":
            return self._build_block_message(request, "security violation detected")
        result = await handler(request)
        if verdict == "warn":
            result = self._append_warn_to_result(result, command)
        return result
