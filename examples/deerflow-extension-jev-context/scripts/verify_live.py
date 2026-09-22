"""Opt-in synthetic Jev + OpenAI-compatible chat smoke test; no real user data.

Run in the backend environment with TYPESAFE_API_KEY, TEST_CHAT_BASE_URL and
TEST_CHAT_MODEL. The chat endpoint is called without an Authorization header.
"""

import asyncio
import json
import os
import sys
from pathlib import Path

import httpx
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.messages.utils import count_tokens_approximately

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from deerflow_extension_jev_context.compaction import MARKER, JevCompaction, Options  # noqa: E402


def history():
    messages = [HumanMessage(content="Read the old test logs, then move on to the release question.", id="u0")]
    for i in range(4):
        messages.extend(
            [
                AIMessage(content="", id=f"a{i}", tool_calls=[{"name": "read_file", "args": {"path": f"/tmp/synthetic-obsolete-log-{i}.txt"}, "id": f"c{i}"}]),
                ToolMessage(content="Obsolete synthetic debug log. This old test run is complete and irrelevant to the release question.\n" * 150, id=f"r{i}", tool_call_id=f"c{i}"),
            ]
        )
    messages.extend(
        [
            AIMessage(content="", id="a-manifest", tool_calls=[{"name": "read_file", "args": {"path": "/tmp/current-release-manifest.txt"}, "id": "c-manifest"}]),
            ToolMessage(
                content="CURRENT RELEASE MANIFEST. The release code is recorded in the middle of this manifest.\n"
                + "Build metadata: checks passed.\n" * 100
                + "\nThe release code is ORCHID.\n"
                + "Build metadata: checks passed.\n" * 100
                + "\nThis is the authoritative current release manifest. Keep it for the release question.",
                id="r-manifest",
                tool_call_id="c-manifest",
            ),
        ]
    )
    messages.extend(
        [
            AIMessage(content="The old test logs have been inspected. That task is complete.", id="done"),
            HumanMessage(content="Ignore the old test logs. Use the current release manifest for the code; the region is eu-west.", id="goal"),
            AIMessage(content="I will use these release facts.", id="ack"),
            HumanMessage(content="The earlier logs are no longer relevant.", id="confirm"),
            AIMessage(content="Ready for the release question.", id="ready"),
            HumanMessage(content="Return only a JSON object with code and region using the earlier release facts.", id="last"),
        ]
    )
    return messages


def wire(messages):
    output = []
    for message in messages:
        if isinstance(message, HumanMessage):
            output.append({"role": "user", "content": message.content})
        elif isinstance(message, ToolMessage):
            output.append({"role": "tool", "content": message.content, "tool_call_id": message.tool_call_id})
        else:
            item = {"role": "assistant", "content": message.content}
            if message.tool_calls:
                item["tool_calls"] = [{"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": json.dumps(c["args"])}} for c in message.tool_calls]
            output.append(item)
    return output


async def main():
    required = ("TYPESAFE_API_KEY", "TEST_CHAT_BASE_URL", "TEST_CHAT_MODEL")
    missing = [name for name in required if not os.environ.get(name, "").strip()]
    if missing:
        raise SystemExit(f"Set {', '.join(missing)} before running this opt-in smoke test")
    base = os.environ["TEST_CHAT_BASE_URL"].rstrip("/")
    model = os.environ["TEST_CHAT_MODEL"]
    original = history()
    options = Options(enabled=True, trigger_tokens=1000, timeout_seconds=30.0)
    update = await JevCompaction(options).abefore_model({"messages": original}, None)
    replacements = {m.id: m for m in (update or {}).get("messages", [])}
    if not replacements:
        raise SystemExit("No pruning: check Jev access/latency or relevance decisions; no savings claim was made")
    assert "r-manifest" not in replacements, "Jev must preserve the still-relevant historical manifest"
    compacted = [replacements.get(m.id, m) for m in original]
    assert all(m.additional_kwargs.get(MARKER) for m in replacements.values())
    assert [m.id for m in compacted] == [m.id for m in original]
    report = {"shortened_results": len(replacements), "estimated_tokens_before": count_tokens_approximately(original), "estimated_tokens_after": count_tokens_approximately(compacted)}
    async with httpx.AsyncClient(timeout=90.0) as client:
        for label, messages in (("baseline", original), ("pruned", compacted)):
            response = await client.post(
                f"{base}/v1/chat/completions",
                json={"model": model, "messages": wire(messages), "temperature": 0, "max_tokens": 512},
            )
            response.raise_for_status()
            data = response.json()
            text = data["choices"][0]["message"]["content"]
            assert "ORCHID" in text and "eu-west" in text, f"{label}: required facts missing"
            report[label] = {"facts_preserved": True, "usage": data.get("usage")}
    # Usage is evidence for this fixture, not a prediction of production cost or
    # cache hit rate. The Jev request is additional work and may be billable.
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
