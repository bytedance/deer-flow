"""One paid image request, with fresh grants and a Gateway-only company key."""

import asyncio
import base64
import json
import threading
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from langchain_core.tools import ToolException

from deerflow.authz.principal import build_principal_from_context
from deerflow.authz.provider import AuthzRequest
from deerflow.authz.user_policy import PROVIDER_PATH, UserAuthorizationProvider
from deerflow.config import get_app_config
from deerflow.config.paths import get_paths
from deerflow.runtime.user_context import get_current_user

from .files import prepare_outputs, read_reference, save_image

_CAPACITY = threading.BoundedSemaphore(2)
MAX_RESPONSE_BYTES = 32 * 1024 * 1024
_USE = "deerflow.community.gpt_image2.tools:gpt_image2_tool"


@dataclass
class Prepared:
    root: Path
    key: str = field(repr=False)
    images: list = field(repr=False, default_factory=list)
    mask: tuple | None = field(repr=False, default=None)


def _prepare(runtime, prompt, size, quality, references, mask):
    if not prompt.strip() or len(prompt) > 16_000:
        raise ToolException("Prompt must contain 1–16000 characters")
    if size not in {"1024x1024", "1536x1024", "1024x1536", "auto"} or quality not in {"low", "medium", "high", "auto"}:
        raise ToolException("Unsupported image size or quality")
    if len(references) > 4 or (mask and not references):
        raise ToolException("Use at most four reference images; a mask requires a reference image")
    config = get_app_config()
    configured = config.get_tool_config("gpt_image2")
    authz = config.authorization
    if configured is None or configured.use != _USE or not authz.enabled or authz.provider is None or authz.provider.use != PROVIDER_PATH:
        raise ToolException("The administrator must configure GPT Image 2 with per-user authorization")
    context = dict(getattr(runtime, "context", None) or {})
    user = get_current_user()
    if user is not None:
        if context.get("user_id") and str(context["user_id"]) != str(user.id):
            raise ToolException("Conflicting user identity")
        context["user_id"] = str(user.id)
        role = getattr(user, "system_role", None) or getattr(user, "role", None)
        if role:
            context["user_role"] = role
    principal = build_principal_from_context(context, default_role="user")
    provider = UserAuthorizationProvider(store_path=authz.provider.config.get("store_path"))
    if not provider.authorize(AuthzRequest(principal, "tool", "call", "gpt_image2")).allow:
        raise ToolException("You are not authorized to use GPT Image 2; ask an administrator for access")
    thread_id = context.get("thread_id") or (getattr(runtime, "config", None) or {}).get("configurable", {}).get("thread_id")
    if not thread_id:
        raise ToolException("A conversation is required for image generation")
    paths = get_paths()
    root = paths.sandbox_user_data_dir(thread_id, user_id=principal.user_id)
    try:
        prepare_outputs(root)
        loaded = [read_reference(root, path) for path in references]
        if sum(len(item[0][1]) for item in loaded) > 40 * 1024 * 1024:
            raise ToolException("Reference images exceed the 40 MiB combined limit")
        mask_file = None
        if mask:
            mask_file, dimensions, alpha = read_reference(root, mask)
            if mask_file[2] != "image/png" or not alpha or dimensions != loaded[0][1]:
                raise ToolException("The mask must be a PNG with alpha and the same dimensions as the first reference")
        key = (paths.base_dir / "security" / "gpt_image2.key").read_text(encoding="utf-8").strip()
        if not key or len(key) > 16384 or any(ord(c) < 33 or ord(c) > 126 for c in key):
            raise ToolException("The company image credential is not configured correctly")
    except OSError:
        raise ToolException("Image configuration or conversation storage is unavailable; contact the administrator") from None
    return Prepared(root, key, [item[0] for item in loaded], mask_file)


def _new_client():
    return httpx.AsyncClient(timeout=httpx.Timeout(300, connect=20), follow_redirects=False)


async def _request(prepared, prompt, size, quality):
    payload = {"model": "gpt-image-2", "prompt": prompt, "size": size, "quality": quality, "n": 1, "output_format": "png"}
    if prepared.images:
        endpoint = "edits"
        files = [("image[]", item) for item in prepared.images]
        if prepared.mask:
            files.append(("mask", prepared.mask))
        params = {"data": {k: str(v) for k, v in payload.items()}, "files": files}
    else:
        endpoint, params = "generations", {"json": payload}
    async with _new_client() as client:
        async with client.stream("POST", f"https://api.openai.com/v1/images/{endpoint}", headers={"Authorization": f"Bearer {prepared.key}"}, **params) as response:
            if response.status_code != 200:
                raise ToolException(f"Image service returned HTTP {response.status_code}. Ask the administrator to check image-model access, billing and limits. No automatic retry was made.")
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > MAX_RESPONSE_BYTES:
                    raise ToolException("Image service response exceeded the size limit")
    return bytes(body)


def _store_response(prepared, body):
    try:
        result = json.loads(body)
        items = result["data"]
        if not isinstance(items, list) or len(items) != 1:
            raise ValueError("Expected one image")
        raw = base64.b64decode(items[0]["b64_json"], validate=True)
    except (ValueError, KeyError, TypeError):
        raise ToolException("Image service did not return a valid image") from None
    return save_image(prepared.root, raw)


async def generate_image(runtime, prompt: str, *, size="1024x1024", quality="medium", reference_images=None, mask=None) -> str:
    if not _CAPACITY.acquire(blocking=False):
        raise ToolException("Image generation is busy (two requests running); try again later")
    try:
        prepared = await asyncio.to_thread(_prepare, runtime, prompt, size, quality, reference_images or [], mask)
        try:
            async with asyncio.timeout(300):
                body = await _request(prepared, prompt, size, quality)
        except (TimeoutError, httpx.TimeoutException):
            raise ToolException("Image generation timed out; it may have been billed. Do not automatically retry.") from None
        except httpx.HTTPError:
            raise ToolException("Image service connection failed; no automatic retry was made. Check request status before trying again.") from None
        return await asyncio.to_thread(_store_response, prepared, body)
    finally:
        _CAPACITY.release()
