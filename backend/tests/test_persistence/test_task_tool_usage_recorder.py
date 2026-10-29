"""Regression tests for _find_usage_recorder callback shape handling.

Bytedance issue #3107 BUG-002: When LangChain passes ``config["callbacks"]`` as
an ``AsyncCallbackManager`` (instead of a plain list), the previous
``for cb in callbacks`` loop raised ``TypeError: 'AsyncCallbackManager' object
is not iterable``. ToolErrorHandlingMiddleware then converted the entire ``task``
tool call into an error ToolMessage, losing the subagent result.
"""

from types import SimpleNamespace

from langchain_core.callbacks import AsyncCallbackManager, CallbackManager

from deerflow.tools.builtins.task_tool import _find_usage_recorder


class _RecorderHandler:
    def record_external_llm_usage_records(self, records):
        self.records = records


class _OtherHandler:
    pass


def _make_runtime(callbacks):
    return SimpleNamespace(config={"callbacks": callbacks})


def test_find_usage_recorder_with_plain_list():
    recorder = _RecorderHandler()
    runtime = _make_runtime([_OtherHandler(), recorder])
    assert _find_usage_recorder(runtime) is recorder


def test_find_usage_recorder_with_async_callback_manager():
    """LangChain wraps callbacks in AsyncCallbackManager for async tool runs.

    The old implementation raised TypeError here. The recorder lives on
    ``manager.handlers``; we must look there too.
    """
    recorder = _RecorderHandler()
    manager = AsyncCallbackManager(handlers=[_OtherHandler(), recorder])
    runtime = _make_runtime(manager)
    assert _find_usage_recorder(runtime) is recorder


def test_find_usage_recorder_with_sync_callback_manager():
    """Sync flavor of the same wrapper used by some langchain code paths."""
    recorder = _RecorderHandler()
    manager = CallbackManager(handlers=[recorder])
    runtime = _make_runtime(manager)
    assert _find_usage_recorder(runtime) is recorder


def test_find_usage_recorder_returns_none_when_no_recorder():
    manager = AsyncCallbackManager(handlers=[_OtherHandler()])
    runtime = _make_runtime(manager)
    assert _find_usage_recorder(runtime) is None


def test_find_usage_recorder_handles_empty_manager():
    manager = AsyncCallbackManager(handlers=[])
    runtime = _make_runtime(manager)
    assert _find_usage_recorder(runtime) is None


def test_find_usage_recorder_returns_none_for_none_runtime():
    assert _find_usage_recorder(None) is None


def test_find_usage_recorder_returns_none_when_callbacks_is_none():
    runtime = _make_runtime(None)
    assert _find_usage_recorder(runtime) is None


def test_find_usage_recorder_returns_none_for_single_handler_object():
    """A single handler instance (not wrapped in a list or manager) should not crash.

    LangChain's contract is that ``config["callbacks"]`` is a list-or-manager,
    but we treat any other shape defensively rather than letting a ``for`` loop
    blow up at runtime.
    """
    runtime = _make_runtime(_RecorderHandler())
    assert _find_usage_recorder(runtime) is None


def test_find_usage_recorder_returns_none_when_config_not_dict():
    """Defensive: a runtime without a dict-shaped config should not raise."""
    runtime = SimpleNamespace(config="not-a-dict")
    assert _find_usage_recorder(runtime) is None
