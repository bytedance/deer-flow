"""Keep documented middleware examples aligned with the locked LangChain API."""

import inspect
import re
from pathlib import Path

import pytest
from langchain.agents.middleware import AgentMiddleware

from deerflow.agents import create_deerflow_agent
from deerflow.client import DeerFlowClient
from deerflow.config.extensions_config import ExtensionsConfig

REPO_ROOT = Path(__file__).resolve().parents[2]
MIDDLEWARE_GUIDES = (
    Path("backend/CONTRIBUTING.md"),
    Path("frontend/src/content/en/harness/customization.mdx"),
    Path("frontend/src/content/en/harness/middlewares.mdx"),
    Path("frontend/src/content/zh/harness/customization.mdx"),
    Path("frontend/src/content/zh/harness/middlewares.mdx"),
)


def _middleware_examples(path: Path) -> list[str]:
    content = (REPO_ROOT / path).read_text(encoding="utf-8")
    examples = [block for block in re.findall(r"```python\n(.*?)\n```", content, flags=re.DOTALL) if "AgentMiddleware" in block and ("class MyMiddleware" in block or "class AuditMiddleware" in block)]
    assert examples, f"no custom middleware example in {path}"
    return examples


@pytest.mark.parametrize("path", MIDDLEWARE_GUIDES, ids=str)
def test_custom_middleware_example_uses_current_lifecycle_hooks(path: Path) -> None:
    for example in _middleware_examples(path):
        namespace: dict[str, object] = {}
        exec(compile(example, str(path), "exec"), namespace)  # noqa: S102 - executes a controlled in-repo documentation example

        middleware_types = [value for value in namespace.values() if isinstance(value, type) and value is not AgentMiddleware and issubclass(value, AgentMiddleware)]
        assert len(middleware_types) == 1

        middleware_type = middleware_types[0]
        assert middleware_type.before_model is not AgentMiddleware.before_model
        assert middleware_type.after_model is not AgentMiddleware.after_model

        middleware = middleware_type()
        assert middleware.before_model({"messages": []}, None) is None
        assert middleware.after_model({"messages": []}, None) is None


def test_documented_registration_apis_exist() -> None:
    ExtensionsConfig.model_validate({"middlewares": ["pkg.mod:MyMiddleware"]})
    assert "middlewares" in inspect.signature(DeerFlowClient.__init__).parameters
    assert "extra_middleware" in inspect.signature(create_deerflow_agent).parameters


@pytest.mark.parametrize("path", MIDDLEWARE_GUIDES, ids=str)
def test_embedded_middleware_scope_is_explicit(path: Path) -> None:
    content = (REPO_ROOT / path).read_text(encoding="utf-8")
    markers = (
        (
            "DeerFlowClient(middlewares=[",
            "builds the full lead-agent chain",
            "create_deerflow_agent(extra_middleware=[",
            "builds a smaller feature-based lead-agent chain",
            "Neither API forwards middleware to subagents.",
        )
        if "/zh/" not in path.as_posix()
        else (
            "DeerFlowClient(middlewares=[",
            "构建完整的主 Agent 链",
            "create_deerflow_agent(extra_middleware=[",
            "构建较小的按功能组装的主 Agent 链",
            "两个 API 均不会将中间件转发给子 Agent。",
        )
    )
    normalized = " ".join(content.split())
    positions = [normalized.index(marker) for marker in markers]
    assert positions == sorted(positions)


@pytest.mark.parametrize("path", MIDDLEWARE_GUIDES, ids=str)
def test_lifecycle_return_contract_is_explicit(path: Path) -> None:
    content = (REPO_ROOT / path).read_text(encoding="utf-8")
    marker = "生命周期钩子可以返回状态更新字典" if "/zh/" in path.as_posix() else "Lifecycle hooks can return a dictionary of state updates"
    assert marker in " ".join(content.split())


@pytest.mark.parametrize("path", MIDDLEWARE_GUIDES, ids=str)
def test_middleware_placement_scope_is_explicit(path: Path) -> None:
    content = (REPO_ROOT / path).read_text(encoding="utf-8")
    marker = (
        "对于主 Agent 链，它位于终态响应、模型长度、安全和澄清尾部之前；子 Agent 链没有终态响应、模型长度或澄清阶段"
        if "/zh/" in path.as_posix()
        else "On the lead-agent pipeline, it runs before the terminal-response, model-length, safety, and clarification tail; subagents have no terminal-response, model-length, or clarification stage"
    )
    assert marker in " ".join(content.split())


@pytest.mark.parametrize(
    "path",
    (
        Path("frontend/src/content/en/harness/middlewares.mdx"),
        Path("frontend/src/content/zh/harness/middlewares.mdx"),
    ),
    ids=str,
)
def test_middleware_order_includes_configured_extension_tail(path: Path) -> None:
    content = " ".join((REPO_ROOT / path).read_text(encoding="utf-8").split())
    markers = (
        (
            "`SkillToolPolicyMiddleware`",
            "Configured extension middlewares (if any)",
            "`TerminalResponseMiddleware`",
            "`ModelLengthFinishReasonMiddleware`",
        )
        if "/en/" in path.as_posix()
        else (
            "`SkillToolPolicyMiddleware`",
            "配置的扩展中间件（如有）",
            "`TerminalResponseMiddleware`",
            "`ModelLengthFinishReasonMiddleware`",
        )
    )
    positions = [content.index(marker) for marker in markers]
    assert positions == sorted(positions)


@pytest.mark.parametrize("path", MIDDLEWARE_GUIDES, ids=str)
def test_subagent_summarization_optionality_is_explicit(path: Path) -> None:
    content = " ".join((REPO_ROOT / path).read_text(encoding="utf-8").split())
    marker = (
        "因此配置中间件之后会继续执行可选的安全防护、`DurableContextMiddleware`、可选的 `SummarizationMiddleware`，随后是 `SubagentDateContextMiddleware` 和 `SystemMessageCoalescingMiddleware`。"
        if "/zh/" in path.as_posix()
        else "so configured middleware is followed by the optional safety guard, `DurableContextMiddleware`, optional `SummarizationMiddleware`, then `SubagentDateContextMiddleware` and `SystemMessageCoalescingMiddleware`."
    )
    assert marker in content


@pytest.mark.parametrize(
    "path",
    (
        Path("frontend/src/content/en/harness/middlewares.mdx"),
        Path("frontend/src/content/zh/harness/middlewares.mdx"),
    ),
    ids=str,
)
def test_runtime_middleware_summary_includes_current_guards(path: Path) -> None:
    content = " ".join((REPO_ROOT / path).read_text(encoding="utf-8").split())
    marker = (
        "运行时中间件（`InputSanitizationMiddleware` 输入清理 → `ToolOutputBudgetMiddleware` 输出预算截断 → "
        "`ToolResultSanitizationMiddleware` 工具结果清理，随后是线程数据、上传、沙箱、悬空工具调用修补和 LLM 错误处理；"
        "工具回执（如启用）、授权/guardrail（如启用）、沙箱审计、读前写后（如启用）、工具进度（如启用）和工具错误处理随后执行）"
        if "/zh/" in path.as_posix()
        else (
            "Runtime middlewares (`InputSanitizationMiddleware` for input sanitization → `ToolOutputBudgetMiddleware` "
            "for output-budget truncation → `ToolResultSanitizationMiddleware` for tool-result sanitization, then thread data, "
            "uploads, sandbox, dangling tool-call patching, and LLM error handling; tool receipts (if enabled), "
            "authorization/guardrail (if enabled), sandbox audit, read-before-write (if enabled), tool progress (if enabled), "
            "and tool error handling follow)"
        )
    )
    assert marker in content


@pytest.mark.parametrize(
    "path",
    (
        Path("frontend/src/content/en/harness/middlewares.mdx"),
        Path("frontend/src/content/zh/harness/middlewares.mdx"),
    ),
    ids=str,
)
def test_runtime_sanitization_and_budget_order_is_explicit(path: Path) -> None:
    content = " ".join((REPO_ROOT / path).read_text(encoding="utf-8").split())
    markers = (
        "`InputSanitizationMiddleware`",
        "`ToolOutputBudgetMiddleware`",
        "`ToolResultSanitizationMiddleware`",
    )
    positions = [content.index(marker) for marker in markers]
    assert positions == sorted(positions)


@pytest.mark.parametrize(
    "path",
    (
        Path("frontend/src/content/en/harness/middlewares.mdx"),
        Path("frontend/src/content/zh/harness/middlewares.mdx"),
    ),
    ids=str,
)
def test_subagent_callout_does_not_overstate_lead_only_scope(path: Path) -> None:
    content = " ".join((REPO_ROOT / path).read_text(encoding="utf-8").split())
    marker = "记忆、标题生成和澄清等其他 Lead Agent 专属中间件不会在子 Agent 链中运行。" if "/zh/" in path.as_posix() else "other Lead-Agent-specific middlewares such as memory, title generation, and clarification do not run there."
    assert marker in content
