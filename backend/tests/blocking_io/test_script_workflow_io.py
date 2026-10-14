"""Workflow worker lifetime and retained records must keep file IO off-loop."""

import os

import pytest
from test_workflow_plugin import context, done, launch
from test_workflow_plugin import plugin as _workflow_fixture

plugin = _workflow_fixture
pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(os.name != "posix", reason="POSIX workflow worker")]


async def test_workflow_lifetime_and_storage_do_not_block_loop(plugin):
    result = await launch(plugin, "log('Finished');return {value:42};")
    final = await done(plugin, result["run_id"])
    assert final["status"] == "completed", final
    assert final["result"] == {"value": 42}
    assert final["logs"] == ["Finished"]
    assert (await plugin[1]["list"]({}, context(plugin[3])))["runs"][0]["run_id"] == result["run_id"]
    await plugin[1]["delete"]({"run_id": result["run_id"]}, context(plugin[3]))
    assert not plugin[2].processes
