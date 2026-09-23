"""Loopback-only browser probe: real asset registration/router, synthetic identity."""

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn
from deerflow_extension_api import BrowserAssets, PluginContribution
from deerflow_extension_api.auth import EXTENSION_PRINCIPAL_RESOLVER_KEY, ExtensionPrincipal
from fastapi import FastAPI

from app.gateway.routers.plugins import router
from deerflow.extensions.registry import ExtensionRegistry


def create_app(directory):
    root = Path(directory)
    (root / "index.mjs").write_text("export default {};")
    (root / "active.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20"><script>document.documentElement.setAttribute("data-executed", "yes")</script><rect width="20" height="20" fill="green"/></svg>')
    (root / "ui_manifest.json").write_text(json.dumps({"schema_version": 1, "entry": "index.mjs", "files": ["index.mjs", "active.svg"]}))
    registry = ExtensionRegistry()
    with registry.attributed_to("browser-probe"):
        registry.plugin(PluginContribution(namespace="test.assets", title="Browser probe", frontend=BrowserAssets("probe.v1", root)))
    app = FastAPI()
    app.state.extensions = registry.build()
    setattr(app.state, EXTENSION_PRINCIPAL_RESOLVER_KEY, lambda request: ExtensionPrincipal("alice") if request.cookies.get("plugin_session") == "synthetic" else None)
    app.include_router(router)
    return app


if __name__ == "__main__":
    with TemporaryDirectory(prefix="deerflow-asset-probe-") as directory:
        uvicorn.run(create_app(directory), host="127.0.0.1", port=int(sys.argv[1]), log_level="warning")
