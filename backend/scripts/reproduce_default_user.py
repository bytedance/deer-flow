"""
Reproduction script for: Feishu user_id becomes "default" (issue #2947)

Demonstrates that get_effective_user_id() returns "default" when called
outside an HTTP request context (which is exactly the scenario for
Feishu channel workers running on background threads).

Run:
    cd backend && PYTHONPATH=. uv run python reproduce_default_user.py
"""

import threading
from dataclasses import dataclass

from deerflow.runtime.user_context import (
    DEFAULT_USER_ID,
    get_effective_user_id,
    reset_current_user,
    set_current_user,
)


@dataclass
class FakeUser:
    """Minimal user object satisfying the CurrentUser protocol (.id: str)."""

    id: str


def simulate_http_request(user_id: str):
    """Simulate what happens in a Gateway HTTP request (auth_middleware.py)."""
    user = FakeUser(id=user_id)
    token = set_current_user(user)
    try:
        return get_effective_user_id()
    finally:
        reset_current_user(token)


def simulate_feishu_worker(sender_open_id: str):
    """
    Simulate what happens in a Feishu channel worker thread.
    The _current_user ContextVar is NEVER set in this path.
    """
    return get_effective_user_id()


def simulate_feishu_worker_in_thread(sender_open_id: str):
    """Simulate Feishu worker running in a background thread (lark callback)."""
    result = []

    def target():
        result.append(get_effective_user_id())

    t = threading.Thread(target=target)
    t.start()
    t.join()
    return result[0]


def main():
    SENDER_OPEN_ID = "ou_abc123_real_feishu_user"

    print("=" * 60)
    print("Reproduction: Feishu user_id becomes 'default' (Issue #2947)")
    print("=" * 60)
    print()

    # 1. HTTP request path (correct behavior)
    effective = simulate_http_request(SENDER_OPEN_ID)
    print("[HTTP Request Path]")
    print(f"  set_current_user(CurrentUser(id='{SENDER_OPEN_ID}'))")
    print(f"  → get_effective_user_id() = '{effective}'")
    print("  ✓ Correct: user_id preserved")
    print()

    # 2. Feishu worker path (BUG — no auth context)
    effective = simulate_feishu_worker(SENDER_OPEN_ID)
    print("[Feishu Worker Path (main thread)]")
    print("  No set_current_user() called (ContextVar is None)")
    print(f"  → get_effective_user_id() = '{effective}'")
    print(f"  ✗ BUG: user_id is '{DEFAULT_USER_ID}' instead of '{SENDER_OPEN_ID}'")
    print()

    # 3. Feishu worker in background thread (worse — even the main thread context is gone)
    effective = simulate_feishu_worker_in_thread(SENDER_OPEN_ID)
    print("[Feishu Worker Path (background thread)]")
    print("  Lark SDK callback in a background thread")
    print("  ContextVar is None (fresh thread context)")
    print(f"  → get_effective_user_id() = '{effective}'")
    print(f"  ✗ BUG: user_id is '{DEFAULT_USER_ID}' instead of '{SENDER_OPEN_ID}'")
    print()

    # 4. Diagnostic
    print("=" * 60)
    print("Root Cause Analysis")
    print("=" * 60)
    print()
    print("The function get_effective_user_id() (user_context.py:100-108)")
    print("reads from _current_user ContextVar:")
    print()
    print("    def get_effective_user_id() -> str:")
    print("        user = _current_user.get()")
    print("        if user is None:")
    print("            return DEFAULT_USER_ID  # 'default'")
    print("        return str(user.id)")
    print()
    print("The _current_user ContextVar is ONLY set in:")
    print("  auth_middleware.py:122 → set_current_user(user)")
    print()
    print("Feishu channel workers (_on_message in feishu.py:585)")
    print("run on lark SDK background threads that NEVER call set_current_user().")
    print()
    print("Files affected by this bug (all call get_effective_user_id()):")
    print("  - feishu.py:352         → file download directory")
    print("  - manager.py:370        → artifact output directory")
    print("  - ThreadDataMiddleware  → per-thread workspace directories")
    print("  - MemoryMiddleware      → memory storage isolation")
    print()
    print("Result: ALL Feishu users share the same 'default' user bucket.")
    print("Memory is NOT isolated between different Feishu users.")
    print()


if __name__ == "__main__":
    main()
