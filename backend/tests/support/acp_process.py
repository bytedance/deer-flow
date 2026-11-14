"""Local ACP processes shared by transport and worker integration tests."""

ACP_AGENT_SCRIPT = """\
import asyncio
import sys
from pathlib import Path

import acp
from acp.schema import InitializeResponse, NewSessionResponse, PromptResponse


class _TestAgent:
    def on_connect(self, conn):
        self._conn = conn

    async def _enter_phase(self, phase):
        Path(sys.argv[3]).write_text(phase, encoding="utf-8")
        if phase == "prompt":
            await self._conn.session_update(session_id="test-session", update=acp.update_agent_thought_text(phase))
        if phase == sys.argv[1]:
            await asyncio.Event().wait()
        delay = float(sys.argv[2])
        if delay:
            await asyncio.sleep(delay)

    async def initialize(self, protocol_version, client_capabilities=None, client_info=None, **kwargs):
        await self._enter_phase("initialize")
        return InitializeResponse(protocol_version=protocol_version)

    async def new_session(self, cwd, additional_directories=None, mcp_servers=None, **kwargs):
        await self._enter_phase("new_session")
        return NewSessionResponse(session_id="test-session")

    async def prompt(self, session_id, prompt, **kwargs):
        await self._enter_phase("prompt")
        return PromptResponse(stop_reason="end_turn")


asyncio.run(acp.run_agent(_TestAgent()))
"""
