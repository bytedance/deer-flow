import asyncio
import logging
import math
import os
import random

import httpx

logger = logging.getLogger(__name__)

_api_key_warned = False


class JinaClient:
    async def crawl(
        self, url: str, return_format: str = "html", timeout: int = 10, proxy: str | None = None, trust_env: bool = True, *, max_retries: int = 0, retry_budget_seconds: float = 30.0, max_response_bytes: int | None = None
    ) -> str:
        """Fetch with optional bounded retries; cancellation always propagates."""
        global _api_key_warned
        headers = {
            "Content-Type": "application/json",
            "X-Return-Format": return_format,
            "X-Timeout": str(timeout),
        }
        if os.getenv("JINA_API_KEY"):
            headers["Authorization"] = f"Bearer {os.getenv('JINA_API_KEY')}"
        elif not _api_key_warned:
            _api_key_warned = True
            logger.warning("Jina API key is not set. Provide your own key to access a higher rate limit. See https://jina.ai/reader for more information.")
        data = {"url": url}
        try:
            if max_response_bytes is not None and (isinstance(max_response_bytes, bool) or not isinstance(max_response_bytes, int) or max_response_bytes <= 0):
                raise ValueError("max_response_bytes must be a positive integer or null")
            if isinstance(max_retries, bool) or not isinstance(max_retries, int) or max_retries < 0:
                raise ValueError("max_retries must be a non-negative integer")
            if isinstance(retry_budget_seconds, bool) or not isinstance(retry_budget_seconds, (int, float)) or not math.isfinite(retry_budget_seconds) or retry_budget_seconds <= 0:
                raise ValueError("retry_budget_seconds must be a finite positive number")

            # HTTPX timeouts are per network phase, so use an outer deadline to
            # bound the complete request sequence (including waits and cleanup).
            deadline = asyncio.get_running_loop().time() + retry_budget_seconds if max_retries else None
            async with asyncio.timeout_at(deadline):
                client_kwargs: dict[str, object] = {"trust_env": trust_env}
                if proxy:
                    client_kwargs["proxy"] = proxy
                async with httpx.AsyncClient(**client_kwargs) as client:
                    delay = 0.5
                    for attempt in range(max_retries + 1):
                        remaining = deadline - asyncio.get_running_loop().time() if deadline is not None else None
                        if remaining is not None and remaining <= 0:
                            raise TimeoutError
                        request_timeout = min(timeout, remaining) if remaining is not None else timeout
                        try:
                            if max_response_bytes is None:
                                response = await client.post("https://r.jina.ai/", headers=headers, json=data, timeout=request_timeout)
                                response_text = response.text
                            else:
                                async with client.stream("POST", "https://r.jina.ai/", headers=headers, json=data, timeout=request_timeout) as response:
                                    content = bytearray()
                                    # aiter_bytes decodes Content-Encoding once. Check before
                                    # retaining each chunk; HTTPX decoder allocations are outside this cap.
                                    async for chunk in response.aiter_bytes():
                                        if len(content) + len(chunk) > max_response_bytes:
                                            return f"Error: Jina API response exceeds max_response_bytes ({max_response_bytes})"
                                        content.extend(chunk)
                                    # Match HTTPX text semantics without decompressing again or
                                    # mutating the response's private buffered-content state.
                                    response_text = content.decode(response.encoding or "utf-8", errors="replace")
                        except (httpx.ConnectError, httpx.ConnectTimeout):
                            if attempt == max_retries:
                                raise
                        else:
                            if response.status_code == 200:
                                if response_text and response_text.strip():
                                    return response_text
                                error_message = "Jina API returned empty response"
                                logger.error(error_message)
                                return f"Error: {error_message}"
                            if response.status_code not in {502, 503, 504} or attempt == max_retries:
                                error_message = f"Jina API returned status {response.status_code}: {response_text}"
                                logger.error(error_message)
                                return f"Error: {error_message}"

                        # Only allowlisted failures reach the non-blocking wait.
                        remaining = deadline - asyncio.get_running_loop().time()
                        if remaining <= 0:
                            raise TimeoutError
                        await asyncio.sleep(min(delay, remaining) * random.uniform(0.5, 1.0))
                        delay = min(delay * 2, 4.0)
        except Exception as e:
            if isinstance(e, TimeoutError) and max_retries and asyncio.get_running_loop().time() >= deadline:
                error_message = "Request to Jina API failed: retry time budget exhausted"
            else:
                error_message = f"Request to Jina API failed: {type(e).__name__}: {e}"
            logger.warning(error_message)
            return f"Error: {error_message}"
