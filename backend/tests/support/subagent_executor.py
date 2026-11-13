"""Shared result doubles and isolated imports for subagent executor tests."""

import importlib
import sys
from contextlib import contextmanager
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock

# Module names that need to be mocked to break circular imports
_MOCKED_MODULE_NAMES = [
    "deerflow.agents",
    "deerflow.agents.thread_state",
    "deerflow.agents.middlewares",
    "deerflow.agents.middlewares.thread_data_middleware",
    "deerflow.sandbox",
    "deerflow.sandbox.middleware",
    "deerflow.sandbox.security",
    "deerflow.models",
    "deerflow.skills.storage",
]


class CompletedResult(SimpleNamespace):
    """An already-completed result for tests without a running producer."""

    def snapshot(self, after_message_index=0):
        return SimpleNamespace(**vars(self), revision=0, message_start_index=0, message_count=len(self.ai_messages))


def default_subagent_app_config():
    return SimpleNamespace(
        tool_search=SimpleNamespace(enabled=False),
        authorization=SimpleNamespace(enabled=False),
        skills=SimpleNamespace(
            deferred_discovery=True,
            container_path="/mnt/skills",
        ),
        skill_evolution=SimpleNamespace(enabled=False),
    )


def patch_default_executor_app_config(executor_module):
    executor_module.get_app_config = default_subagent_app_config
    return executor_module


def _clear_stale_executor_package_attr() -> None:
    subagents_pkg = sys.modules.get("deerflow.subagents")
    if subagents_pkg is not None and hasattr(subagents_pkg, "executor"):
        delattr(subagents_pkg, "executor")


@contextmanager
def real_executor_classes():
    """Set up mocked modules and import real executor classes.

    Yield the executor classes for a single isolated test.
    It handles module cleanup to avoid affecting other test files.
    """
    # Save original modules
    original_modules = {name: sys.modules.get(name) for name in _MOCKED_MODULE_NAMES}
    original_executor = sys.modules.get("deerflow.subagents.executor")
    original_audit_context = sys.modules.get("deerflow.agents.middlewares.audit_context")
    original_tool_declarations = sys.modules.get("deerflow.agents.middlewares.tool_declarations")
    original_tool_search = sys.modules.get("deerflow.tools.builtins.tool_search")
    original_sandbox_provider = sys.modules.get("deerflow.sandbox.sandbox_provider")
    original_sandbox_overwrite = sys.modules.get("deerflow.sandbox.overwrite")
    original_sandbox_prewarm = sys.modules.get("deerflow.sandbox.prewarm")

    # Preload real executor dependencies before replacing their parent packages
    # with cycle-breaking test doubles. Keeping the concrete leaf modules in
    # sys.modules makes this fixture independent of test collection order.
    audit_context_module = importlib.import_module("deerflow.agents.middlewares.audit_context")
    tool_declarations_module = importlib.import_module("deerflow.agents.middlewares.tool_declarations")
    tool_search_module = importlib.import_module("deerflow.tools.builtins.tool_search")
    sandbox_provider_module = importlib.import_module("deerflow.sandbox.sandbox_provider")
    sandbox_overwrite_module = importlib.import_module("deerflow.sandbox.overwrite")
    sandbox_prewarm_module = importlib.import_module("deerflow.sandbox.prewarm")
    for module_name in ("deerflow.models.factory", "deerflow.models.openai_codex_provider", "deerflow.agents.assembly_descriptor", "deerflow.agents.middlewares.tool_call_args", "deerflow.agents.lead_agent.agent"):
        importlib.import_module(module_name)

    # Remove mocked executor if exists (from conftest.py)
    if "deerflow.subagents.executor" in sys.modules:
        del sys.modules["deerflow.subagents.executor"]
    _clear_stale_executor_package_attr()

    # Set up mocks
    for name in _MOCKED_MODULE_NAMES:
        sys.modules[name] = MagicMock()
    storage_module = ModuleType("deerflow.skills.storage")
    storage_module.get_or_new_skill_storage = lambda **kwargs: SimpleNamespace(load_skills=lambda *, enabled_only: [])
    storage_module.get_or_new_user_skill_storage = lambda user_id, **kwargs: SimpleNamespace(load_skills=lambda *, enabled_only: [])
    sys.modules["deerflow.skills.storage"] = storage_module
    sys.modules["deerflow.agents.middlewares.audit_context"] = audit_context_module
    sys.modules["deerflow.agents.middlewares.tool_declarations"] = tool_declarations_module
    sys.modules["deerflow.tools.builtins.tool_search"] = tool_search_module
    sys.modules["deerflow.sandbox.sandbox_provider"] = sandbox_provider_module
    sys.modules["deerflow.sandbox.overwrite"] = sandbox_overwrite_module
    sys.modules["deerflow.sandbox.prewarm"] = sandbox_prewarm_module

    # Import real classes inside fixture
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

    from deerflow.subagents.config import SubagentConfig
    from deerflow.subagents.executor import (
        SubagentExecutor,
        SubagentResult,
        SubagentStatus,
    )

    executor_module = sys.modules["deerflow.subagents.executor"]

    # Executor control-flow tests patch _create_agent. Keep those tests
    # hermetic: CI checkouts do not include
    # the gitignored config.yaml, and deferral-specific tests override this
    # default explicitly.
    patch_default_executor_app_config(executor_module)

    # Store classes in a dict to yield
    classes = {
        "AIMessage": AIMessage,
        "HumanMessage": HumanMessage,
        "ToolMessage": ToolMessage,
        "SubagentConfig": SubagentConfig,
        "SubagentExecutor": SubagentExecutor,
        "SubagentResult": SubagentResult,
        "SubagentStatus": SubagentStatus,
    }

    try:
        yield classes
    finally:
        # Cleanup: Restore original modules
        for name in _MOCKED_MODULE_NAMES:
            if original_modules[name] is not None:
                sys.modules[name] = original_modules[name]
            elif name in sys.modules:
                del sys.modules[name]

        # Restore executor module (conftest.py mock)
        if original_executor is not None:
            sys.modules["deerflow.subagents.executor"] = original_executor
        elif "deerflow.subagents.executor" in sys.modules:
            del sys.modules["deerflow.subagents.executor"]
        if original_audit_context is not None:
            sys.modules["deerflow.agents.middlewares.audit_context"] = original_audit_context
        else:
            sys.modules.pop("deerflow.agents.middlewares.audit_context", None)
        if original_tool_declarations is not None:
            sys.modules["deerflow.agents.middlewares.tool_declarations"] = original_tool_declarations
        else:
            sys.modules.pop("deerflow.agents.middlewares.tool_declarations", None)
        if original_tool_search is not None:
            sys.modules["deerflow.tools.builtins.tool_search"] = original_tool_search
        else:
            sys.modules.pop("deerflow.tools.builtins.tool_search", None)
        if original_sandbox_provider is not None:
            sys.modules["deerflow.sandbox.sandbox_provider"] = original_sandbox_provider
        else:
            sys.modules.pop("deerflow.sandbox.sandbox_provider", None)
        if original_sandbox_overwrite is not None:
            sys.modules["deerflow.sandbox.overwrite"] = original_sandbox_overwrite
        else:
            sys.modules.pop("deerflow.sandbox.overwrite", None)
        if original_sandbox_prewarm is not None:
            sys.modules["deerflow.sandbox.prewarm"] = original_sandbox_prewarm
        else:
            sys.modules.pop("deerflow.sandbox.prewarm", None)
