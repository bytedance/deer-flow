"""Verify the built distribution, outside the example's source import path."""

import argparse
import asyncio
import importlib.metadata
import inspect
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installed-dir", required=True, type=Path)
    args = parser.parse_args()
    installed = args.installed_dir.resolve(strict=True)
    sys.path.insert(0, str(installed))

    from deerflow_extension_api import AgentBuildContext, AgentScope
    from deerflow_extension_api.auth import ExtensionPrincipal
    from deerflow_extension_api.plugins import ActionContext

    from deerflow.extensions.loader import ExtensionSpec, load_extensions

    distribution = importlib.metadata.distribution("deerflow-extension-jev-context")
    assert Path(distribution.locate_file("")).resolve() == installed
    entries = [entry for entry in distribution.entry_points if entry.group == "deerflow.extensions"]
    assert [(entry.name, entry.value) for entry in entries] == [("jev-context", "deerflow_extension_jev_context:install")]
    installer = entries[0].load()
    assert callable(installer)
    assert Path(inspect.getfile(installer)).resolve().is_relative_to(installed)
    assert distribution.metadata["License-Expression"] == "MIT"
    assert distribution.metadata.get_all("License-File") == ["LICENSE"]
    license_file = next(file for file in distribution.files if str(file).endswith(".dist-info/licenses/LICENSE"))
    assert "DeerFlow Authors" in distribution.locate_file(license_file).read_text(encoding="utf-8")

    for enabled in (False, True):
        loaded, diagnostics = load_extensions([ExtensionSpec(use=entries[0].value, config={"enabled": enabled})])
        assert not diagnostics, diagnostics
        ((_, plugin),) = loaded.plugins
        assert plugin.namespace == "community.jev-context" and plugin.enabled == enabled
        ((_, contributor),) = loaded.middleware_contributors
        assert bool(contributor.contribute_middlewares(None, AgentBuildContext(scope=AgentScope.LEAD))) == enabled
        assert not contributor.contribute_middlewares(None, AgentBuildContext(scope=AgentScope.SUBAGENT))
        (action,) = plugin.backend
        status = asyncio.run(action.handler({}, ActionContext(ExtensionPrincipal("package-test"), {})))
        assert set(status) == {"enabled", "configured", "trigger_tokens"}
        assert status["enabled"] == enabled
    print("Installed wheel entry point, license, host registration and enable/disable verified.")


if __name__ == "__main__":
    main()
