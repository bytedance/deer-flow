"""Template: a tests/blocking_io/ runtime anchor.

Copy into backend/tests/blocking_io/test_<area>.py and adapt. The suite's
conftest already wraps every test here in the strict Blockbuster gate, so you do
NOT import or activate the detector — just drive the real async entry point.

Teeth check before you commit (see references/good-anchor-rules.md):
  1. reintroduce the block  -> `cd backend && make test-blocking-io` must FAIL
  2. restore the fix        -> it must PASS
"""

from __future__ import annotations

from pathlib import Path

import pytest

# from app.<module> import <real_async_entry_point>

pytestmark = pytest.mark.asyncio


async def test_<entry_point>_offloads_blocking_io_on_<branch>(tmp_path: Path) -> None:
    # Arrange: real inputs at the boundary the code blocks on (FS -> tmp_path;
    #   HTTP/subprocess -> stub the external service). Mock ONLY the external
    #   boundary, never the offload under test.

    # Act + Assert: call the REAL production async entry point and drive the
    # specific branch you are guarding (e.g. force a failure to hit the cleanup
    # path). If the entry point performs blocking IO on the loop, the gate fails.
    #   await <real_async_entry_point>(...)
    raise NotImplementedError("Replace with the real async entry point call.")
