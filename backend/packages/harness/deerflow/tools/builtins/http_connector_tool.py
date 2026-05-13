"""Built-in tool for calling pre-configured HTTP endpoints."""

from __future__ import annotations

import logging
import os
import time

import httpx
from langchain.tools import tool

from deerflow.config import get_app_config
from deerflow.config.tenant import get_current_tenant_id

logger = logging.getLogger(__name__)


@tool("http_connector", parse_docstring=True)
async def http_connector_tool(
    connector_name: str,
    params: dict | None = None,
    body: dict | None = None,
) -> str:
    """Call a pre-configured HTTP endpoint by name to fetch external data.

    Use this tool to interact with external APIs that have been pre-configured
    by the platform administrator. Only connectors defined in the system
    configuration can be called.

    Args:
        connector_name: Name of the configured connector to invoke.
        params: Optional query parameters (for GET) or body merge fields (for POST/PUT).
        body: Optional JSON request body for POST/PUT methods.

    Returns:
        The HTTP response body as a string, or an error message.
    """
    tenant_id = get_current_tenant_id()
    config = get_app_config()
    connector = config.get_http_connector(tenant_id, connector_name)

    if connector is None:
        available = config.list_connector_names(tenant_id)
        if available:
            return f"Error: Unknown connector '{connector_name[:100]}'. Available connectors: {available}"
        return "Error: No HTTP connectors configured for this tenant."

    # HIGH: Fail early if auth is configured but token is missing
    if connector.auth_type != "none" and connector.auth_token_env:
        token = os.environ.get(connector.auth_token_env, "")
        if not token:
            return f"Error: Auth token environment variable '{connector.auth_token_env}' is not set for connector '{connector_name[:100]}'."

    headers = connector.resolved_headers()
    headers.setdefault("Accept", "application/json")

    # MEDIUM: Validate agent-supplied params/body size
    MAX_PARAMS_KEYS = 50
    MAX_BODY_KEYS = 100
    if params and len(params) > MAX_PARAMS_KEYS:
        return f"Error: params exceeds maximum of {MAX_PARAMS_KEYS} keys."
    if body and len(body) > MAX_BODY_KEYS:
        return f"Error: body exceeds maximum of {MAX_BODY_KEYS} keys."

    # Check cache if TTL is configured
    from deerflow.tools.builtins.http_connector_cache import get_connector_cache
    cache = get_connector_cache()
    if connector.cache_ttl_seconds:
        cached = cache.get(tenant_id, connector_name, params, body)
        if cached is not None:
            logger.info("http_connector cache hit", extra={"connector_name": connector_name, "tenant_id": tenant_id})
            return cached

    max_attempts = connector.max_retries + 1
    last_error: str | None = None

    for attempt in range(max_attempts):
        start_time = time.monotonic()
        status_code = 0
        response_size = 0
        truncated = False

        try:
            async with httpx.AsyncClient(timeout=connector.timeout_seconds) as client:
                if connector.method.upper() == "GET":
                    resp = await client.get(connector.url, headers=headers, params=params)
                elif connector.method.upper() == "POST":
                    json_body = {**(body or {}), **(params or {})} if params else body
                    resp = await client.post(connector.url, headers=headers, json=json_body)
                elif connector.method.upper() == "PUT":
                    json_body = {**(body or {}), **(params or {})} if params else body
                    resp = await client.put(connector.url, headers=headers, json=json_body)
                else:
                    return f"Error: Unsupported HTTP method '{connector.method}'"

            status_code = resp.status_code
            latency_ms = (time.monotonic() - start_time) * 1000
            raw_bytes = resp.content
            response_size = len(raw_bytes)

            if status_code in connector.retry_on_status and attempt < max_attempts - 1:
                last_error = f"HTTP {status_code}"
                logger.warning(
                    "http_connector retry",
                    extra={
                        "connector_name": connector_name,
                        "tenant_id": tenant_id,
                        "status_code": status_code,
                        "attempt": attempt + 1,
                        "latency_ms": round(latency_ms, 1),
                    },
                )
                continue

            if response_size > connector.max_response_bytes:
                raw_bytes = raw_bytes[: connector.max_response_bytes]
                truncated = True

            response_text = raw_bytes.decode("utf-8", errors="replace")

            log_level = logging.WARNING if latency_ms > 10000 else logging.INFO
            logger.log(
                log_level,
                "http_connector call",
                extra={
                    "connector_name": connector_name,
                    "tenant_id": tenant_id,
                    "status_code": status_code,
                    "latency_ms": round(latency_ms, 1),
                    "response_size": response_size,
                    "truncated": truncated,
                    "retry_count": attempt,
                },
            )

            if resp.is_success:
                result = response_text
                if truncated:
                    result = response_text + "\n\n[Response truncated due to size limit]"
                # Write to cache on success if TTL configured
                if connector.cache_ttl_seconds and not truncated:
                    cache.put(tenant_id, connector_name, params, body, result, connector.cache_ttl_seconds)
                return result

            # MEDIUM: Don't echo raw error body to agent — log it server-side only
            logger.warning(
                "http_connector non-success response",
                extra={
                    "connector_name": connector_name,
                    "tenant_id": tenant_id,
                    "status_code": status_code,
                    "response_body_preview": response_text[:500],
                },
            )
            return f"Error: HTTP {status_code} from connector '{connector_name[:100]}'. Check server logs for details."

        except httpx.TimeoutException:
            latency_ms = (time.monotonic() - start_time) * 1000
            last_error = "timeout"
            logger.warning(
                "http_connector timeout",
                extra={
                    "connector_name": connector_name,
                    "tenant_id": tenant_id,
                    "timeout_seconds": connector.timeout_seconds,
                    "attempt": attempt + 1,
                    "latency_ms": round(latency_ms, 1),
                },
            )
            if attempt < max_attempts - 1:
                continue
        except httpx.HTTPError as exc:
            latency_ms = (time.monotonic() - start_time) * 1000
            last_error = str(exc)
            logger.error(
                "http_connector error",
                extra={
                    "connector_name": connector_name,
                    "tenant_id": tenant_id,
                    "error": str(exc),
                    "attempt": attempt + 1,
                    "latency_ms": round(latency_ms, 1),
                },
            )
            if attempt < max_attempts - 1:
                continue

    return f"Error: Failed to call connector '{connector_name}' after {max_attempts} attempts. Last error: {last_error}"
