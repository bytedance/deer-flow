"""
Image Generation Tool — kie.ai Z-Image model (async).

Flow:
1. Generates a local UUID as tracking_id.
2. Registers tracking_id with the gateway (so it's ready to accept the callback).
3. Creates ONE task on kie.ai with callBackUrl = PUBLIC_HOST/api/image-tasks/{tracking_id}/callback
4. kie.ai processes the image and POSTs the result to our callBackUrl.
5. The gateway stores the result under tracking_id.
6. The tool polls the gateway by tracking_id until success or timeout.

All HTTP calls are async so the LangGraph event loop is never blocked.
"""

import asyncio
import json
import logging
import uuid

import httpx
from langchain.tools import tool

from src.config import get_app_config

logger = logging.getLogger(__name__)

KIE_API_BASE = "https://api.kie.ai/api/v1/jobs"

# Public URL where kie.ai sends callbacks (reachable from the internet)
_PUBLIC_CALLBACK_HOST = "http://82.208.20.46:2026"

# Internal gateway URL (reachable from within Docker network)
_GATEWAY_INTERNAL = "http://gateway:8001"

POLL_INTERVAL = 4   # seconds between gateway polls
MAX_WAIT = 180      # total timeout in seconds


def _get_api_key() -> str:
    config = get_app_config().get_tool_config("generate_image")
    if config is not None:
        key = config.model_extra.get("api_key", "")
        if key and not key.startswith("$"):
            return key
    raise ValueError(
        "kie.ai API key not configured. Add 'api_key: $KIE_AI_API_KEY' to the "
        "generate_image tool entry in config.yaml and set KIE_AI_API_KEY in .env."
    )


async def _register_with_gateway(client: httpx.AsyncClient, tracking_id: str) -> None:
    resp = await client.post(
        f"{_GATEWAY_INTERNAL}/api/image-tasks/{tracking_id}/register",
        timeout=10,
    )
    resp.raise_for_status()
    logger.debug("Tracking ID %s registered with gateway", tracking_id)


async def _create_task(
    client: httpx.AsyncClient,
    api_key: str,
    prompt: str,
    aspect_ratio: str,
    tracking_id: str,
) -> str:
    callback_url = f"{_PUBLIC_CALLBACK_HOST}/api/image-tasks/{tracking_id}/callback"
    payload = {
        "model": "z-image",
        "input": {
            "prompt": prompt[:1000],
            "aspect_ratio": aspect_ratio,
        },
        "callBackUrl": callback_url,
    }
    resp = await client.post(
        f"{KIE_API_BASE}/createTask",
        json=payload,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 200:
        raise RuntimeError(f"createTask failed: {data.get('message', data)}")
    kie_task_id = data["data"]["taskId"]
    logger.info(
        "kie.ai task created: kie_id=%s tracking_id=%s callback=%s",
        kie_task_id, tracking_id, callback_url,
    )
    return kie_task_id


async def _poll_gateway(client: httpx.AsyncClient, tracking_id: str) -> list[str]:
    deadline = asyncio.get_event_loop().time() + MAX_WAIT
    while asyncio.get_event_loop().time() < deadline:
        try:
            resp = await client.get(
                f"{_GATEWAY_INTERNAL}/api/image-tasks/{tracking_id}",
                timeout=10,
            )
            if resp.status_code == 404:
                logger.debug("Tracking ID %s not found, retrying…", tracking_id)
                await asyncio.sleep(POLL_INTERVAL)
                continue
            resp.raise_for_status()
            data = resp.json()
            status = data.get("status")

            if status == "success":
                urls = data.get("urls", [])
                logger.info("Image task %s succeeded: %s", tracking_id, urls)
                return urls
            elif status == "fail":
                raise RuntimeError(f"Image generation failed: {data.get('error', 'unknown')}")
            elif status == "unknown":
                raise RuntimeError(f"Unexpected callback payload: {data.get('error')}")

            logger.debug("Task %s still pending…", tracking_id)

        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            logger.warning("Gateway poll error (will retry): %s", e)

        await asyncio.sleep(POLL_INTERVAL)

    raise TimeoutError(f"Image generation timed out after {MAX_WAIT}s (tracking_id={tracking_id})")


@tool("generate_image", parse_docstring=True)
async def generate_image_tool(
    prompt: str,
    aspect_ratio: str = "1:1",
) -> str:
    """Generate an image from a text description using the Z-Image AI model.

    Use this tool whenever the user asks to create, draw, generate, or visualize an image.
    The tool returns direct URLs to the generated images — include them in your response
    as markdown images: ![description](url)

    **Supported aspect ratios:**
    - "1:1"  — square (social media posts, avatars)
    - "4:3"  — landscape standard (presentations, screens)
    - "3:4"  — portrait standard (posters, cards)
    - "16:9" — wide landscape (banners, wallpapers, YouTube thumbnails)
    - "9:16" — tall portrait (Stories, Reels, TikTok)

    **Prompt tips:**
    - Be descriptive: include style, lighting, mood, composition, camera/film references
    - Specify art style if needed: "photorealistic", "oil painting", "anime", "watercolor"
    - Good example: "A hyperrealistic photo of a steaming espresso cup on a marble table,
      morning sunlight, shallow depth of field, shot on Leica M6, Kodak Portra 400"

    Args:
        prompt: Detailed text description of the image to generate. Max 1000 characters.
        aspect_ratio: Output image ratio. One of: "1:1", "4:3", "3:4", "16:9", "9:16". Default "1:1".
    """
    valid_ratios = {"1:1", "4:3", "3:4", "16:9", "9:16"}
    if aspect_ratio not in valid_ratios:
        return json.dumps(
            {"error": f"Invalid aspect_ratio '{aspect_ratio}'. Must be one of: {sorted(valid_ratios)}"},
            ensure_ascii=False,
        )

    try:
        api_key = _get_api_key()
        tracking_id = str(uuid.uuid4())

        async with httpx.AsyncClient() as client:
            await _register_with_gateway(client, tracking_id)
            await _create_task(client, api_key, prompt, aspect_ratio, tracking_id)
            urls = await _poll_gateway(client, tracking_id)

        if not urls:
            return json.dumps({"error": "Generation succeeded but returned no image URLs."}, ensure_ascii=False)

        return json.dumps(
            {
                "status": "success",
                "image_urls": urls,
                "usage_hint": (
                    "Embed the images in your response using markdown: "
                    "![description](url). Show all returned URLs."
                ),
            },
            indent=2,
            ensure_ascii=False,
        )

    except TimeoutError as e:
        logger.error("Image generation timeout: %s", e)
        return json.dumps({"error": str(e)}, ensure_ascii=False)
    except Exception as e:
        logger.error("Image generation error: %s", e)
        return json.dumps({"error": str(e)}, ensure_ascii=False)
