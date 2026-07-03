import asyncio
import ipaddress
import logging
import os
import re
import socket
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated
from urllib.parse import urlparse

from langchain.tools import InjectedToolCallId, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from deerflow.config import get_app_config
from deerflow.config.paths import VIRTUAL_PATH_PREFIX
from deerflow.tools.types import Runtime
from deerflow.utils.readability import ReadabilityExtractor

from .browserless_client import BrowserlessClient, BrowserlessScreenshotResult

logger = logging.getLogger(__name__)

# readability_extractor runs CPU-bound parsing; always call via asyncio.to_thread
_readability_extractor = ReadabilityExtractor()
_OUTPUTS_VIRTUAL_PREFIX = f"{VIRTUAL_PATH_PREFIX}/outputs"
_OUTPUT_FORMAT_TO_EXTENSION = {
    "png": "png",
    "jpeg": "jpeg",
    "webp": "webp",
}
_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
# Hostnames that always resolve to a loopback/link-local/cloud-metadata target.
_BLOCKED_HOSTNAMES = {"localhost", "metadata.google.internal"}
# Cap collision-suffix probing so a saturated outputs directory cannot spin forever.
_MAX_FILENAME_COLLISION_PROBES = 1000


def _get_tool_config(tool_name: str) -> dict | None:
    """Get tool config extras safely, returning None if not configured."""
    config = get_app_config().get_tool_config(tool_name)
    if config is None:
        return None
    extras = config.model_extra
    return extras if extras is not None else {}


def _get_browserless_client(tool_name: str = "web_fetch") -> BrowserlessClient:
    cfg = _get_tool_config(tool_name)
    base_url = "http://localhost:3032"
    token = os.getenv("BROWSERLESS_TOKEN", "")
    timeout_s = 30.0
    if cfg is not None:
        base_url = cfg.get("base_url", base_url)
        token = cfg.get("token", token)
        raw = cfg.get("timeout_s", timeout_s)
        timeout_s = float(raw) if not isinstance(raw, float) else raw
    return BrowserlessClient(base_url=base_url, token=token, timeout_s=timeout_s)


def _as_bool(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return default


def _as_int(value: object, default: int) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return default
    return default


def _as_optional_quality(value: object, output_format: str) -> int | None:
    if output_format not in {"jpeg", "webp"}:
        return None
    quality = _as_int(value, -1)
    return quality if 0 <= quality <= 100 else None


def _normalize_output_format(value: object) -> str:
    output_format = str(value or "png").strip().lower()
    return output_format if output_format in _OUTPUT_FORMAT_TO_EXTENSION else "png"


def _resolve_host_addresses(hostname: str) -> list[ipaddress._BaseAddress]:
    """Resolve a hostname to all of its IP addresses for SSRF screening.

    Returns an empty list when resolution fails so callers can decide how to
    treat an unresolvable host.
    """
    addresses: list[ipaddress._BaseAddress] = []
    try:
        infos = socket.getaddrinfo(hostname, None)
    except (socket.gaierror, UnicodeError):
        return addresses
    for info in infos:
        sockaddr = info[4]
        try:
            addresses.append(ipaddress.ip_address(sockaddr[0]))
        except ValueError:
            continue
    return addresses


def _is_blocked_address(address: ipaddress._BaseAddress) -> bool:
    """Return True for addresses that must never be reachable via this tool."""
    return address.is_private or address.is_loopback or address.is_link_local or address.is_reserved or address.is_multicast or address.is_unspecified


def _validate_capture_url(url: str, allow_private_addresses: bool = False) -> str | None:
    """Validate a capture URL for scheme and (unless opted out) SSRF safety.

    Blocks requests that resolve to loopback, private, link-local (incl. the
    169.254.169.254 cloud-metadata endpoint), reserved, multicast, or
    unspecified addresses. Operators who intentionally point the tool at an
    internal Browserless target can opt out via ``allow_private_addresses``.
    """
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return "Error: Only http:// and https:// URLs are supported"

    if allow_private_addresses:
        return None

    hostname = parsed.hostname
    if not hostname:
        return "Error: URL host could not be parsed"

    normalized_host = hostname.strip().rstrip(".").lower()
    if normalized_host in _BLOCKED_HOSTNAMES:
        return "Error: Refusing to capture a private or loopback address"

    # A literal IP host is screened directly; a name is screened across every
    # address it resolves to, so a DNS record pointing at an internal IP is
    # rejected rather than blindly fetched.
    try:
        literal_ip = ipaddress.ip_address(normalized_host)
    except ValueError:
        literal_ip = None

    if literal_ip is not None:
        candidates = [literal_ip]
    else:
        candidates = _resolve_host_addresses(hostname)
        if not candidates:
            return "Error: URL host could not be resolved"

    if any(_is_blocked_address(addr) for addr in candidates):
        return "Error: Refusing to capture a private, loopback, or metadata address"
    return None


def _default_capture_stem(url: str) -> str:
    parsed = urlparse(url)
    parts = [parsed.netloc, *[part for part in parsed.path.split("/") if part]]
    raw = "-".join(parts) or "web-capture"
    return raw[:80]


def _safe_capture_filename(filename: str | None, url: str, output_format: str) -> str:
    extension = _OUTPUT_FORMAT_TO_EXTENSION[output_format]
    if filename:
        raw_name = Path(filename).name
        stem = Path(raw_name).stem or "web-capture"
    else:
        timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        stem = f"{_default_capture_stem(url)}-{timestamp}"

    safe_stem = _SAFE_FILENAME_RE.sub("_", stem).strip("._-") or "web-capture"
    return f"{safe_stem[:100]}.{extension}"


def _thread_outputs_path(runtime: Runtime) -> Path | str:
    if runtime.state is None:
        return "Error: Thread runtime state is not available"
    thread_data = runtime.state.get("thread_data") or {}
    outputs_path = thread_data.get("outputs_path")
    if not outputs_path:
        return "Error: Thread outputs path is not available"
    return Path(outputs_path)


def _tool_message(content: str, tool_call_id: str) -> Command:
    return Command(update={"messages": [ToolMessage(content, tool_call_id=tool_call_id)]})


def _dedupe_output_name(outputs_path: Path, output_name: str) -> str:
    """Return a non-colliding filename under ``outputs_path``.

    Keeps the original name when free, otherwise appends ``-1``, ``-2``, ...
    before the extension so an explicit filename never silently overwrites an
    earlier capture. Falls back to a timestamp suffix if the directory is
    saturated with the bounded probe range.
    """
    candidate = outputs_path / output_name
    if not candidate.exists():
        return output_name

    stem = Path(output_name).stem
    suffix = Path(output_name).suffix
    for index in range(1, _MAX_FILENAME_COLLISION_PROBES + 1):
        probe = f"{stem}-{index}{suffix}"
        if not (outputs_path / probe).exists():
            return probe

    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
    return f"{stem}-{timestamp}{suffix}"


def _write_capture_output(outputs_path: Path, output_name: str, content: bytes) -> str:
    """Write ``content`` into ``outputs_path`` and return the actual filename used."""
    outputs_path.mkdir(parents=True, exist_ok=True)
    final_name = _dedupe_output_name(outputs_path, output_name)
    (outputs_path / final_name).write_bytes(content)
    return final_name


def _target_status_warning(result: BrowserlessScreenshotResult) -> str:
    """Return a human-readable warning when the captured page itself errored.

    Browserless returns HTTP 200 for the render request even when the target
    page responded with a 4xx/5xx (or was an error/anti-bot page), so the raw
    image alone cannot be trusted as valid visual evidence. The target's real
    status is surfaced via the X-Response-Code header.
    """
    code = result.target_status_code.strip()
    if not code or code.startswith(("2", "3")):
        return ""
    status = result.target_status.strip()
    detail = f"{code} {status}".strip()
    return f" (warning: target page responded {detail})"


@tool("web_fetch", parse_docstring=True)
async def web_fetch_tool(url: str) -> str:
    """Fetch the contents of a web page at a given URL using Browserless (headless Chrome).
    Only fetch EXACT URLs that have been provided directly by the user or have been returned in results from the web_search and web_fetch tools.
    This tool can NOT access content that requires authentication, such as private Google Docs or pages behind login walls.
    Do NOT add www. to URLs that do NOT have them.
    URLs must include the schema: https://example.com is a valid URL while example.com is an invalid URL.

    Args:
        url: The URL to fetch the contents of.
    """
    try:
        cfg = _get_tool_config("web_fetch")

        wait_for_event = ""
        wait_for_timeout_ms = 0
        wait_for_selector = ""
        wait_for_selector_timeout_ms = 5000
        reject_resource_types: list[str] | None = None
        reject_request_pattern: list[str] | None = None

        if cfg is not None:
            wait_for_event = cfg.get("wait_for_event", wait_for_event)
            raw_wait = cfg.get("wait_for_timeout_ms", wait_for_timeout_ms)
            wait_for_timeout_ms = int(raw_wait) if not isinstance(raw_wait, int) else raw_wait
            wait_for_selector = cfg.get("wait_for_selector", wait_for_selector)

        client = _get_browserless_client("web_fetch")
        html = await client.fetch_html(
            url=url,
            wait_for_event=wait_for_event,
            wait_for_timeout_ms=wait_for_timeout_ms,
            wait_for_selector=wait_for_selector,
            wait_for_selector_timeout_ms=wait_for_selector_timeout_ms,
            reject_resource_types=reject_resource_types,
            reject_request_pattern=reject_request_pattern,
        )

        if html.startswith("Error:"):
            return html

        article = await asyncio.to_thread(_readability_extractor.extract_article, html)
        return article.to_markdown()[:4096]

    except Exception as e:
        logger.error(f"Error in web_fetch_tool: {e}")
        return f"Error: {str(e)}"


@tool("web_capture", parse_docstring=True)
async def web_capture_tool(
    runtime: Runtime,
    url: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
    filename: str | None = None,
    full_page: bool | None = None,
    output_format: str | None = None,
    viewport_width: int | None = None,
    viewport_height: int | None = None,
) -> Command:
    """Capture a rendered webpage screenshot and present it as an artifact.

    Use this tool when you need a visual capture of a public webpage, especially JavaScript-heavy pages, UI states, dashboards, or visual evidence for a report.
    Only capture exact URLs provided by the user or discovered through other tools. Do not use this for private pages behind login unless the user has explicitly configured Browserless outside DeerFlow.
    URLs must include the schema: https://example.com is valid while example.com is invalid.

    Args:
        url: The http(s) URL to capture.
        filename: Optional output filename. Directories are ignored and the extension is determined by output_format.
        full_page: Optional override for full-page capture.
        output_format: Optional image format: png, jpeg, or webp.
        viewport_width: Optional viewport width in pixels.
        viewport_height: Optional viewport height in pixels.
    """
    try:
        cfg = _get_tool_config("web_capture") or {}
        allow_private_addresses = _as_bool(cfg.get("allow_private_addresses"), False)

        url_error = _validate_capture_url(url, allow_private_addresses=allow_private_addresses)
        if url_error:
            return _tool_message(url_error, tool_call_id)

        outputs_path = _thread_outputs_path(runtime)
        if isinstance(outputs_path, str):
            return _tool_message(outputs_path, tool_call_id)

        final_format = _normalize_output_format(output_format or cfg.get("output_format", "png"))
        final_full_page = full_page if full_page is not None else _as_bool(cfg.get("full_page"), True)
        final_width = viewport_width if viewport_width is not None else _as_int(cfg.get("viewport_width"), 1280)
        final_height = viewport_height if viewport_height is not None else _as_int(cfg.get("viewport_height"), 720)
        quality = _as_optional_quality(cfg.get("quality"), final_format)
        wait_for_selector = str(cfg.get("wait_for_selector") or "")
        wait_for_selector_timeout_ms = _as_int(cfg.get("wait_for_selector_timeout_ms"), 5000)
        wait_for_timeout_ms = _as_int(cfg.get("wait_for_timeout_ms"), 0)
        best_attempt = _as_bool(cfg.get("best_attempt"), False)

        output_name = _safe_capture_filename(filename, url, final_format)

        client = _get_browserless_client("web_capture")
        result = await client.capture_screenshot(
            url=url,
            full_page=final_full_page,
            output_format=final_format,
            quality=quality,
            viewport={"width": final_width, "height": final_height},
            wait_for_selector=wait_for_selector,
            wait_for_selector_timeout_ms=wait_for_selector_timeout_ms,
            wait_for_timeout_ms=wait_for_timeout_ms,
            best_attempt=best_attempt,
        )
        if isinstance(result, str):
            return _tool_message(result, tool_call_id)

        final_name = await asyncio.to_thread(_write_capture_output, outputs_path, output_name, result.content)
        virtual_path = f"{_OUTPUTS_VIRTUAL_PREFIX}/{final_name}"
        message = f"Captured screenshot: {virtual_path}{_target_status_warning(result)}"
        return Command(
            update={
                "artifacts": [virtual_path],
                "messages": [ToolMessage(message, tool_call_id=tool_call_id)],
            }
        )

    except Exception as e:
        logger.error(f"Error in web_capture_tool: {e}")
        return _tool_message(f"Error: {str(e)}", tool_call_id)
