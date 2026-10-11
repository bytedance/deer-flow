"""Operator-configured, read-only synthetic material for the scheduled pilot."""

import asyncio

from langchain.tools import tool

from .protocol import PROTOCOL, fixture


@tool
async def read_scheduled_fixture(case_id: str) -> dict:
    """Read one named synthetic pilot document; never read arbitrary files or URLs."""
    case = await asyncio.to_thread(fixture, case_id)
    return {"synthetic": True, "protocol": PROTOCOL, "case_id": case_id, **case["source"]}
