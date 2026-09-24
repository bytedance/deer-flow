"""Authenticated discovery and execution for deployment-installed full-stack plugins."""

import asyncio
import hashlib
import json
import logging
from types import MappingProxyType

from deerflow_extension_api.auth import resolve_principal
from fastapi import APIRouter, HTTPException, Request, Response

from deerflow.extensions.browser_assets import LoadedBrowserAssets, valid_asset_path
from deerflow.extensions.plugin_tools import plugin_settings

router = APIRouter(prefix="/api/plugins", tags=["plugins"])
logger = logging.getLogger(__name__)


def _principal(request):
    principal = resolve_principal(request)
    if principal is None:
        raise HTTPException(401, "Authentication required.")
    return principal


@router.get("")
async def list_plugins(request: Request, response: Response):
    principal = _principal(request)
    response.headers["Cache-Control"] = "private, no-store"
    entries = []
    for source, plugin in request.app.state.extensions.plugins:
        settings = plugin_settings(source, plugin)
        module = plugin.frontend
        if isinstance(module, LoadedBrowserAssets):
            revision = module.revision
            entry = f"/api/plugins/{plugin.namespace}/assets/{revision}/{module.entry}"
            transport = "assets-v1"
        else:
            revision = hashlib.sha256(module.code.encode()).hexdigest() if module else None
            entry = f"/api/plugins/modules/{module.module}/{revision}.mjs" if module else None
            transport = "inline-v1" if module else None
        public = ("enabled", *module.public_fields) if module else ("enabled",)
        entries.append(
            {
                "namespace": plugin.namespace,
                "title": plugin.title,
                "description": plugin.description,
                "viewer_id": principal.user_id,
                "module": module.module if module else None,
                "entry": entry,
                "transport": transport,
                "settings": {key: settings[key] for key in public},
                "backend_actions": [action.name for action in plugin.backend],
            }
        )
    return entries


@router.get("/modules/{module}/{revision}.mjs")
async def plugin_module(request: Request, module: str, revision: str):
    _principal(request)
    for _, plugin in request.app.state.extensions.plugins:
        if plugin.frontend and not isinstance(plugin.frontend, LoadedBrowserAssets) and plugin.frontend.module == module:
            code = plugin.frontend.code.encode()
            if hashlib.sha256(code).hexdigest() == revision:
                return Response(code, media_type="text/javascript", headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})
    raise HTTPException(404, "Plugin module unavailable; reload the page.")


@router.get("/{namespace}/assets/{revision}/{path:path}")
async def plugin_asset(request: Request, namespace: str, revision: str, path: str):
    _principal(request)
    if valid_asset_path(path):
        for _, plugin in request.app.state.extensions.plugins:
            module = plugin.frontend
            if plugin.namespace == namespace and isinstance(module, LoadedBrowserAssets) and module.revision == revision:
                asset = module.files.get(path)
                if asset is not None:
                    return Response(
                        asset.content,
                        media_type=asset.media_type,
                        headers={
                            "Cache-Control": "private, max-age=31536000, immutable",
                            "Vary": "Cookie, Authorization",
                            "X-Content-Type-Options": "nosniff",
                            # Assets can also be opened as documents (notably SVG).
                            "Content-Security-Policy": "sandbox",
                        },
                    )
    raise HTTPException(404, "Plugin asset unavailable; reload the page.", headers={"Cache-Control": "private, no-store"})


@router.post("/{namespace}/actions/{action_name}")
async def invoke_plugin_action(request: Request, namespace: str, action_name: str):
    """Invoke an installed action with the authenticated viewer and deployment settings."""
    from deerflow_extension_api.auth import resolve_principal
    from deerflow_extension_api.plugins import ActionContext

    from deerflow.extensions.plugin_tools import plugin_settings

    principal = resolve_principal(request)
    if principal is None:
        raise HTTPException(401, "Authentication required.")
    if request.headers.get("x-deerflow-plugin-viewer") not in (None, principal.user_id):
        raise HTTPException(409, "Account changed; reload this plugin view.")
    found = next(((source, plugin) for source, plugin in request.app.state.extensions.plugins if plugin.namespace == namespace), None)
    if found is None:
        raise HTTPException(404, "Plugin is not installed.")
    source, plugin = found
    action = next((item for item in plugin.backend if item.name == action_name), None)
    if action is None:
        raise HTTPException(404, "Plugin action is not installed.")
    try:
        settings = await asyncio.to_thread(plugin_settings, source, plugin)
    except (ValueError, OSError) as exc:
        raise HTTPException(503, "Plugin settings unavailable.") from exc
    if settings["enabled"] is not True:
        raise HTTPException(403, "Plugin disabled by administrator.")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 256 * 1024:
            raise HTTPException(413, "Plugin action input exceeds 256 KiB.")
    try:
        payload = json.loads(body)
        if not isinstance(payload, dict):
            raise ValueError("Expected an object")
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(422, "Plugin action requires a JSON object.") from exc
    try:
        async with asyncio.timeout(30):
            return await action.handler(MappingProxyType(payload), ActionContext(principal, MappingProxyType(settings)))
    except TimeoutError as exc:
        raise HTTPException(504, "Plugin action timed out.") from exc
    except ValueError as exc:
        raise HTTPException(422, "Invalid plugin action input.") from exc
    except Exception as exc:
        logger.warning("Plugin action failed: %s/%s (%s)", namespace, action_name, type(exc).__name__)
        raise HTTPException(502, "Plugin action failed.") from exc
