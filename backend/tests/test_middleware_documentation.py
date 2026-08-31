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


def _middleware_example(path: Path) -> str:
    content = (REPO_ROOT / path).read_text(encoding="utf-8")
    examples = [block for block in re.findall(r"```python\n(.*?)\n```", content, flags=re.DOTALL) if "AgentMiddleware" in block and ("class MyMiddleware" in block or "class AuditMiddleware" in block)]
    assert len(examples) == 1, f"expected one custom middleware example in {path}"
    return examples[0]


@pytest.mark.parametrize("path", MIDDLEWARE_GUIDES, ids=str)
def test_custom_middleware_example_uses_current_lifecycle_hooks(path: Path) -> None:
    namespace: dict[str, object] = {}
    example = _middleware_example(path)
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
    marker = "这两个嵌入式 API 仅作用于主 Agent 链" if "/zh/" in path.as_posix() else "Both embedded APIs affect only the lead-agent pipeline"
    assert marker in " ".join(content.split())


@pytest.mark.parametrize("path", MIDDLEWARE_GUIDES, ids=str)
def test_lifecycle_return_contract_is_explicit(path: Path) -> None:
    content = (REPO_ROOT / path).read_text(encoding="utf-8")
    marker = "生命周期钩子可以返回状态更新字典" if "/zh/" in path.as_posix() else "Lifecycle hooks can return a dictionary of state updates"
    assert marker in " ".join(content.split())
