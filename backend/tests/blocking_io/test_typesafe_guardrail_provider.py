"""Anchor: the TypeSafe guardrail's async path must not block the event loop.

``aevaluate`` is the path ``GuardrailMiddleware.awrap_tool_call`` awaits, so any
blocking call inside it stalls every other task on the loop. This anchor drives
it against a **real loopback HTTP server** — a socket-level peer, not a
``MockTransport`` — because a mock never touches ``socket.recv`` and would stay
green even if the async path were rewritten to use a synchronous client.

Teeth: ``test_sync_evaluate_on_the_loop_trips_the_gate`` runs the provider's
*sync* path against the same server from inside the loop. Blockbuster raises
``BlockingError`` there because the blocking socket calls happen with a
``deerflow`` frame on the stack. That is exactly the failure a regression
(``aevaluate`` delegating to ``evaluate``) would produce, so the green test
above cannot pass vacuously.

The provider creates its client per evaluation from ``transport_factory``; this
anchor uses the default (no factory) so the traffic runs over a real socket.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator

import pytest
from blockbuster import BlockingError

from deerflow.guardrails.provider import GuardrailRequest
from deerflow.guardrails.typesafe import TypeSafeGuardrailProvider

pytestmark = pytest.mark.asyncio

_RESPONSE = {
    "model": "jev-1.13.0",
    "answers": {"risky_tool_call": {"type": "noul", "noul": 0.93}},
    "usage": {"input_tokens": 12, "output_tokens": 2},
}


async def _answer_once(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """Serve exactly one canned System One response over a real socket."""
    header_lines: list[bytes] = []
    while True:
        line = await reader.readline()
        if not line or line in (b"\r\n", b"\n"):
            break
        header_lines.append(line)
    length = 0
    for line in header_lines[1:]:
        name, _, value = line.decode("latin-1").partition(":")
        if name.strip().lower() == "content-length":
            length = int(value.strip())
    if length:
        await reader.readexactly(length)
    payload = json.dumps(_RESPONSE).encode()
    writer.write(b"HTTP/1.1 200 OK\r\ncontent-type: application/json\r\nconnection: close\r\ncontent-length: %d\r\n\r\n%s" % (len(payload), payload))
    await writer.drain()
    writer.close()


@contextlib.asynccontextmanager
async def _typesafe_endpoint() -> AsyncIterator[str]:
    server = await asyncio.start_server(_answer_once, host="127.0.0.1", port=0)
    try:
        port = server.sockets[0].getsockname()[1]
        yield f"http://127.0.0.1:{port}"
    finally:
        server.close()
        await server.wait_closed()


def _dangerous_call() -> GuardrailRequest:
    return GuardrailRequest(tool_name="bash", tool_input={"command": "rm -rf /tmp/scratch"})


async def test_aevaluate_over_a_real_socket_stays_off_the_loop() -> None:
    async with _typesafe_endpoint() as base_url:
        provider = TypeSafeGuardrailProvider(api_key="anchor-key", base_url=base_url, retry_backoff=0)
        decision = await provider.aevaluate(_dangerous_call())

    assert decision.allow is False
    assert decision.reasons[0].code == "typesafe.tool_call_risky"
    assert decision.metadata["model"] == "jev-1.13.0"


async def test_allowed_tools_refusal_stays_local_under_strict_blocking_io() -> None:
    """The refusal branch runs before any state is built.

    Driven under the strict Blockbuster gate, touching a socket or a client here
    would fail the anchor: a refused tool is answered without network setup.
    """
    provider = TypeSafeGuardrailProvider(api_key="anchor-key", allowed_tools=["bash"])
    decision = await provider.aevaluate(GuardrailRequest(tool_name="read_file", tool_input={"path": "a.txt"}))

    assert decision.allow is False
    assert decision.reasons[0].code == "typesafe.tool_not_allowed"


async def test_sync_evaluate_on_the_loop_trips_the_gate() -> None:
    """Meta-check (teeth): the sync path blocks, so a loop-blocking regression fails."""
    async with _typesafe_endpoint() as base_url:
        provider = TypeSafeGuardrailProvider(api_key="anchor-key", base_url=base_url, retry_backoff=0)
        with pytest.raises(BlockingError):
            provider.evaluate(_dangerous_call())
