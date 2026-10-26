"""One atomic, process-local Web request counter shared across a run's tools.

The HTTPX request hook reserves before transport, including redirect hops and
retries. Counters are registered by the trusted run worker and removed at run
cleanup; model arguments cannot choose or reset the limit.
"""

from threading import Lock
from typing import Any


class WebAttemptBudgetExceeded(Exception):
    """The local run has no first-party Web HTTP attempts remaining."""


class _Counter:
    def __init__(self, limit: int):
        self.limit = limit
        self.used = 0
        self.lock = Lock()

    def reserve(self) -> None:
        with self.lock:
            if self.used >= self.limit:
                raise WebAttemptBudgetExceeded("Run Web request budget exhausted")
            self.used += 1


_lock = Lock()
_counters: dict[str, _Counter] = {}


def register_run(run_id: str, limit: int | None) -> None:
    """Pin a fresh policy for a trusted run, if configured."""
    if limit is None:
        return
    with _lock:
        if run_id in _counters:
            raise ValueError("Run Web request budget already registered")
        _counters[run_id] = _Counter(limit)


def unregister_run(run_id: str) -> None:
    with _lock:
        _counters.pop(run_id, None)


def counter_for_config(config: Any) -> _Counter | None:
    context = None
    policy_context = None
    if isinstance(config, dict):
        configurable = config.get("configurable", {})
        if isinstance(configurable, dict):
            runtime = configurable.get("__pregel_runtime")
            context = getattr(runtime, "context", None)
            policy_context = configurable.get("context")
            if not isinstance(context, dict):
                context = policy_context
        if not isinstance(context, dict):
            context = config.get("context")
    if not isinstance(context, dict):
        return None
    run_id = context.get("run_id")
    if not isinstance(run_id, str):
        return None
    with _lock:
        counter = _counters.get(run_id)
    if counter is not None:
        return counter
    # A child running in another process cannot see the parent's local
    # counter. Deny rather than silently treating its attempts as unlimited.
    app_config = context.get("app_config") or (policy_context.get("app_config") if isinstance(policy_context, dict) else None)
    policy = getattr(app_config, "web_attempt_budget", None)
    if getattr(policy, "max_attempts", None) is not None:
        return _Counter(0)
    return None
