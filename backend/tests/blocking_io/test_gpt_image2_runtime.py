"""Company image authorization and file I/O must not block the Gateway loop."""

import asyncio

import pytest
from test_gpt_image2 import env, grant, png  # noqa: F401


@pytest.mark.asyncio
async def test_generation_offloads_policy_credentials_and_image_files(env):  # noqa: F811
    await asyncio.to_thread(grant, env)
    output = await env.service.generate_image(env.runtime, "a tree")

    def check_output():
        target = env.paths.resolve_virtual_path("thread-one", output, user_id="alice")
        assert target.read_bytes() == png()

    await asyncio.to_thread(check_output)
    assert len(env.calls) == 1
