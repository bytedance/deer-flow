# SPDX-License-Identifier: MIT
"""Browser captures must not be published half written under the final name."""

from __future__ import annotations

import inspect

from deerflow.community.browser_automation import tools as browser_automation_tools
from deerflow.community.browserless import tools as browserless_tools


def test_screenshot_writes_go_through_the_atomic_publish():
    source = inspect.getsource(browser_automation_tools)

    # A truncating write left a partial capture behind while the function returned
    # the name as if it had been saved.
    assert "(outputs_path / name).write_bytes(" not in source
    assert "_publish_bytes_atomically(outputs_path / name, content)" in source


def test_capture_writes_go_through_the_atomic_publish():
    source = inspect.getsource(browserless_tools)

    assert "(outputs_path / final_name).write_bytes(" not in source
    assert "_publish_bytes_atomically(outputs_path / final_name, content)" in source


def test_both_helpers_publish_through_a_temporary_file():
    for module in (browser_automation_tools, browserless_tools):
        source = inspect.getsource(module)
        assert "def _publish_bytes_atomically(" in source
        assert "os.replace(temporary, path)" in source
