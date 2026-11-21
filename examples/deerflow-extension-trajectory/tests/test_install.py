"""Exercise the installed distribution, not a manually imported install function."""

import json
import os
from importlib.metadata import distribution
from pathlib import Path

import pytest

from deerflow.extensions.loader import ExtensionSpec, load_extensions


def test_installed_entry_point_registers_routes_and_packaged_browser_assets():
    dist = distribution("deerflow-extension-trajectory")
    entries = [
        entry for entry in dist.entry_points if entry.group == "deerflow.extensions"
    ]
    assert [(entry.name, entry.value) for entry in entries] == [
        ("trajectory", "deerflow_extension_trajectory:install")
    ]
    install = entries[0].load()
    assert callable(install)
    if os.environ.get("TRAJECTORY_REQUIRE_WHEEL") == "1":
        import deerflow_extension_trajectory

        assert (
            Path(deerflow_extension_trajectory.__file__)
            .resolve()
            .is_relative_to(Path(dist.locate_file("")).resolve())
        )
        assert (
            not json.loads(dist.read_text("direct_url.json") or "{}")
            .get("dir_info", {})
            .get("editable")
        )
    loaded, diagnostics = load_extensions(
        [ExtensionSpec(use=entries[0].value, required=True)]
    )
    assert not diagnostics
    assert len(loaded.routers) == len(loaded.plugins) == 1
    paths = {route.path for _, router in loaded.routers for route in router.routes}
    assert paths == {
        "/api/ext-trajectory/threads/{thread_id}/checkpoints",
        "/api/ext-trajectory/threads/{thread_id}/compaction",
        "/api/ext-trajectory/threads/{thread_id}/export",
        "/api/ext-trajectory/threads/{thread_id}/subagents",
        "/api/ext-trajectory/threads/{thread_id}/subagent-checkpoints",
    }
    plugin = loaded.plugins[0][1]
    assert plugin.namespace == "community.trajectory"
    assert plugin.enabled
    assert len(loaded.documentation) == 1
    documentation = loaded.documentation[0][1]
    assert documentation["id"] == plugin.namespace
    assert set(documentation["locales"]) == {"en-US", "zh-CN"}
    assert all(copy["usage"] for copy in documentation["locales"].values())
    assert len(loaded.middleware_contributors) == 1
    assert not loaded.services
    root = plugin.frontend.root
    manifest = json.loads((root / "ui_manifest.json").read_text(encoding="utf-8"))
    assert manifest["entry"] == "static/dist/index.mjs"
    for name in manifest["files"]:
        assert (root / name).is_file()


def test_install_rejects_hosts_without_full_stack_plugin_support():
    class UnsupportedRegistry:
        def routers(self, routers):
            assert len(routers) == 1

        def plugin(self, contribution):
            return False

    entry = next(
        entry
        for entry in distribution("deerflow-extension-trajectory").entry_points
        if entry.group == "deerflow.extensions"
    )
    with pytest.raises(RuntimeError, match="全栈插件契约"):
        entry.load()(UnsupportedRegistry(), {})
