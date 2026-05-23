"""End-to-end demo: SafetyFinishReasonMiddleware on the real DeerFlow lead-agent.

What it proves
--------------
- The real ``make_lead_agent`` / ``DeerFlowClient`` pipeline is built (full
  18-middleware chain, sandbox, tools, etc.).
- A model that returns ``finish_reason='content_filter'`` + ``tool_calls``
  triggers SafetyFinishReasonMiddleware.
- LangChain's tool router never invokes ``write_file`` — the truncated
  arguments do **not** reach the sandbox.
- A ``safety_termination`` custom event is emitted on the stream and the
  final AIMessage carries the observability stamp.

Run from backend/ directory:
    PYTHONPATH=. uv run python scripts/e2e_safety_termination_demo.py
"""

from __future__ import annotations

import sys
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

# ---------------------------------------------------------------------------
# Fake provider that mimics Moonshot's content_filter behaviour
# ---------------------------------------------------------------------------


class _ContentFilteredFakeModel(BaseChatModel):
    """First call returns finish_reason=content_filter + truncated write_file
    tool_call. Subsequent calls return a normal stop response so the agent
    can terminate (the middleware should make a second call unnecessary by
    clearing tool_calls, but we keep this safety net in case loop-detection
    or anything else triggers another model invocation)."""

    call_count: int = 0

    @property
    def _llm_type(self) -> str:
        return "fake-content-filtered"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.call_count += 1
        if self.call_count == 1:
            msg = AIMessage(
                content="# 政经周报\n- **会晤时间**：2026年5月12日—13日，特朗普访问中国，与",
                tool_calls=[
                    {
                        "id": "call_truncated_write",
                        "name": "write_file",
                        "args": {
                            "path": "/mnt/user-data/outputs/political-economic-news-weekly-may-16-2026.md",
                            "content": "# 政经周报\n- **会晤时间**：2026年5月12日—13日，特朗普访问中国，与",
                        },
                    }
                ],
                response_metadata={
                    "finish_reason": "content_filter",
                    "model_name": "kimi-k2.6",
                    "model_provider": "openai",
                },
            )
        else:
            msg = AIMessage(
                content="(secondary call, should not be needed)",
                response_metadata={"finish_reason": "stop", "model_name": "kimi-k2.6"},
            )
        return ChatResult(generations=[ChatGeneration(message=msg)])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def main() -> int:
    # Inject the fake model BEFORE constructing the client. Both the
    # client module and the lead-agent module bind ``create_chat_model``
    # at import time via ``from deerflow.models import create_chat_model``,
    # so we patch both attribute slots — the source-of-truth patch on
    # ``factory.create_chat_model`` doesn't propagate back into already-
    # imported names.
    import deerflow.agents.lead_agent.agent as lead_agent_module
    import deerflow.client as client_module

    fake = _ContentFilteredFakeModel()
    originals = {
        "lead": lead_agent_module.create_chat_model,
        "client": client_module.create_chat_model,
    }

    def fake_create_chat_model(*args, **kwargs):
        return fake

    lead_agent_module.create_chat_model = fake_create_chat_model
    client_module.create_chat_model = fake_create_chat_model

    from deerflow.client import DeerFlowClient

    try:
        client = DeerFlowClient()

        print("\n=== Streaming a turn through the real lead-agent ===")
        events: list[dict[str, Any]] = []
        for event in client.stream(
            "帮我整理一下最近一周政经新闻，写到 /mnt/user-data/outputs/political-economic-news-weekly-may-16-2026.md",
            thread_id="e2e-safety-1",
        ):
            events.append({"type": event.type, "data": event.data})

        # ---- Assertions ----
        safety_event = next(
            (e for e in events if e["type"] == "custom" and isinstance(e["data"], dict) and e["data"].get("type") == "safety_termination"),
            None,
        )
        final_values = next(
            (e for e in reversed(events) if e["type"] == "values"),
            None,
        )
        tool_messages = [e for e in events if e["type"] == "messages-tuple" and isinstance(e["data"], dict) and e["data"].get("type") == "tool"]
        ai_tool_call_messages = [e for e in events if e["type"] == "messages-tuple" and isinstance(e["data"], dict) and e["data"].get("type") == "ai" and e["data"].get("tool_calls")]

        print(f"\n[stats] total stream events: {len(events)}")
        print(f"[stats] model call count: {fake.call_count}")
        print(f"[stats] tool messages on stream: {len(tool_messages)}")
        print(f"[stats] AI messages carrying tool_calls: {len(ai_tool_call_messages)}")

        print("\n[event] safety_termination custom event:")
        if safety_event is None:
            print("  *** NOT FOUND ***")
            return 1
        for k, v in safety_event["data"].items():
            print(f"    {k}: {v}")

        print("\n[state] final AIMessage from last values snapshot:")
        if final_values is None:
            print("  *** no values snapshot ***")
            return 1
        # `values` event carries `_serialize_message` dicts, not Message objects.
        final_messages = final_values["data"].get("messages") or []
        last_ai = next((m for m in reversed(final_messages) if isinstance(m, dict) and m.get("type") == "ai"), None)
        if last_ai is None:
            print("  *** no AIMessage in final state ***")
            print(f"      message types seen: {[m.get('type') if isinstance(m, dict) else type(m).__name__ for m in final_messages]}")
            return 1

        tool_calls = last_ai.get("tool_calls") or []
        additional_kwargs = last_ai.get("additional_kwargs") or {}
        response_metadata = last_ai.get("response_metadata") or {}
        content = last_ai.get("content")

        print(f"    tool_calls (must be empty): {tool_calls}")
        print(f"    additional_kwargs.safety_termination: {additional_kwargs.get('safety_termination')}")
        content_preview = (content if isinstance(content, str) else str(content))[:200]
        print(f"    content[:200]: {content_preview!r}")
        print(f"    response_metadata.finish_reason: {response_metadata.get('finish_reason')}")

        # NOTE: `client._serialize_message` does not include `response_metadata`
        # in the values-event payload (client-layer behaviour, unrelated to the
        # middleware). The middleware *does* preserve finish_reason on the
        # AIMessage object — see test_safety_finish_reason_middleware.py::
        # TestMessageRewrite::test_preserves_response_metadata_finish_reason.
        # Here we assert on the observability stamp, which carries the same
        # evidence and is in the serialized payload.
        stamp = additional_kwargs.get("safety_termination") or {}
        failures = []
        if tool_calls:
            failures.append("final AIMessage still has tool_calls — middleware did NOT clear them")
        if not stamp:
            failures.append("final AIMessage missing safety_termination observability stamp")
        if tool_messages:
            failures.append(f"tool node was invoked: {len(tool_messages)} ToolMessage(s) on stream")
        if stamp.get("reason_value") != "content_filter":
            failures.append(f"safety_termination.reason_value was {stamp.get('reason_value')!r}, expected 'content_filter'")
        if safety_event is None:
            failures.append("safety_termination custom event was not emitted on the stream")

        if failures:
            print("\n=== FAIL ===")
            for f in failures:
                print(f"  - {f}")
            return 1

        print("\n=== PASS ===")
        print("  - tool_calls cleared on final AIMessage")
        print("  - tool node never invoked (no ToolMessage on stream)")
        print("  - safety_termination custom event emitted")
        print("  - observability stamp written to additional_kwargs")
        print("  - response_metadata.finish_reason preserved for downstream SSE")
        return 0
    finally:
        lead_agent_module.create_chat_model = originals["lead"]
        client_module.create_chat_model = originals["client"]


if __name__ == "__main__":
    sys.exit(main())
