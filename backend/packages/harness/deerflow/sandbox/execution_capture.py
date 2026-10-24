"""Optional server-owned physical capture, inherited only by one execution.

This observes acquired resources. It grants no business or provider ownership
and never reconstructs execution identity from checkpoint or request fields.
"""

from contextlib import contextmanager
from contextvars import ContextVar

_capture = ContextVar("deerflow_sandbox_execution_capture", default=None)


def current_execution_capture():
    return _capture.get()


@contextmanager
def sandbox_execution_capture(observer):
    token = _capture.set(observer)
    try:
        yield observer
    finally:
        _capture.reset(token)


@contextmanager
def capture_acquisition(provider, thread_id, user_id):
    observer = current_execution_capture()
    if observer is None:
        yield lambda sandbox_id: None
        return
    observer.acquire_started(thread_id, user_id)
    try:
        yield lambda sandbox_id: observer.observe(provider, sandbox_id, acquiring=True)
    except BaseException:
        observer.acquire_failed()
        raise
    else:
        observer.acquire_ended()
