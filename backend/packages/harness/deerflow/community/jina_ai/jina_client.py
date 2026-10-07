import asyncio
import logging
import math
import os
import random
import re
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx

logger = logging.getLogger(__name__)

_api_key_warned = False


_DAY = r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)"
_MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
_CLOCK = r"[0-9]{2}:[0-9]{2}:[0-9]{2}"
_HTTP_DATE = re.compile(
    rf"(?:{_DAY}, [0-9]{{2}} {_MONTH} [0-9]{{4}} {_CLOCK} GMT"
    rf"|(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday), [0-9]{{2}}-{_MONTH}-[0-9]{{2}} {_CLOCK} GMT"
    rf"|{_DAY} {_MONTH} (?:[0-9]{{2}}| [0-9]) {_CLOCK} [0-9]{{4}})"
)


def _retry_after(value: str | None) -> float | None:
    """Return a server floor, or None for an invalid HTTP Retry-After value."""
    if value is None:
        return None
    value = value.strip(" \t")
    if value and value.isascii() and value.isdecimal():
        digits = value.lstrip("0") or "0"
        # Bound integer conversion work. Infinity is a valid, unfit floor, not
        # a parsing failure that could cause an early fallback retry.
        if len(digits) > 309:
            return math.inf
        seconds = int(digits)
        try:
            floor = float(seconds)
        except OverflowError:
            return math.inf
        return math.nextafter(floor, math.inf) if floor < seconds else floor
    if not _HTTP_DATE.fullmatch(value):
        return None
    try:
        date = parsedate_to_datetime(value).replace(tzinfo=UTC)
        now = time.time()
        if "-" in value:
            # RFC 850 two-digit years: choose the most recent matching year
            # no more than 50 years in the future (RFC 9110 section 5.6.7).
            current = datetime.fromtimestamp(now, UTC)
            year = (current.year + 50) // 100 * 100 + date.year % 100
            if (year, date.month, date.day, date.hour, date.minute, date.second) > (current.year + 50, current.month, current.day, current.hour, current.minute, current.second):
                year -= 100
            date = date.replace(year=year)
        return max(0.0, date.timestamp() - now)
    except (ValueError, OverflowError):
        return None


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
                        server_floor = None
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
                            if response.status_code in {429, 503} and attempt < max_retries:
                                server_floor = _retry_after(response.headers.get("Retry-After"))
                            retryable = response.status_code in {502, 503, 504} or (response.status_code == 429 and server_floor is not None)
                            if not retryable or attempt == max_retries:
                                error_message = f"Jina API returned status {response.status_code}: {response_text}"
                                logger.error(error_message)
                                return f"Error: {error_message}"

                        # Only allowlisted failures reach the non-blocking wait.
                        remaining = deadline - asyncio.get_running_loop().time()
                        if server_floor is not None and server_floor >= remaining:
                            return f"Error: Jina API returned status {response.status_code}: {response_text}"
                        if remaining <= 0:
                            raise TimeoutError
                        wait = min(delay, remaining) * random.uniform(0.5, 1.0)
                        if server_floor is not None:
                            wait = max(wait, server_floor)
                            if wait >= remaining:
                                return f"Error: Jina API returned status {response.status_code}: {response_text}"
                        await asyncio.sleep(wait)
                        delay = min(delay * 2, 4.0)
        except Exception as e:
            if isinstance(e, TimeoutError) and max_retries and asyncio.get_running_loop().time() >= deadline:
                error_message = "Request to Jina API failed: retry time budget exhausted"
            else:
                error_message = f"Request to Jina API failed: {type(e).__name__}: {e}"
            logger.warning(error_message)
            return f"Error: {error_message}"
