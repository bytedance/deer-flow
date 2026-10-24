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


async def test_definition_and_live_checkpoint_storage_do_not_block_loop(plugin):
    from test_workflow_plugin import waiting

    actions, runs = plugin[1], plugin[3]
    definition = await actions["save_definition"]({"name": "pause", "script": "await pause({stepId:'p'});return 42;"}, context(runs))
    assert (await actions["definitions"]({}, context(runs)))["definitions"] == [definition]
    launched = await actions["launch"]({"request_id": "saved", "definition": definition}, context(runs))
    run_id = launched["run_id"]
    paused = await waiting(plugin, run_id, "paused")
    await actions["resume"]({"run_id": run_id, "step_id": "p", "attempt": 1, "fingerprint": paused["fingerprint"]}, context(runs))
    assert (await done(plugin, run_id))["result"] == 42


async def test_file_capture_review_consumption_do_not_block_loop(plugin):
    from test_workflow_plugin import test_immutable_file_review_and_downstream_consume_same_version

    await test_immutable_file_review_and_downstream_consume_same_version(plugin)
