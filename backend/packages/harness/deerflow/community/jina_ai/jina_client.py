import asyncio
import logging
import math
import os
import random
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx

logger = logging.getLogger(__name__)

_api_key_warned = False


def _parse_retry_after(value: str | None, *, now: datetime | None = None) -> float | None:
    """Return a valid Retry-After delay without overflowing on large integers."""
    if not value:
        return None
    value = value.strip()
    if value.isascii() and value.isdigit():
        seconds = value.lstrip("0")
        if not seconds:
            return 0.0
        # A delay beyond this range is already much larger than any useful
        # retry budget; infinity makes it safely non-retryable under a deadline.
        if len(seconds) > 18:
            return math.inf
        return float(int(seconds))

    try:
        retry_at = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if retry_at.tzinfo is None:
        return None
    current_time = now or datetime.now(UTC)
    return max(0.0, (retry_at.astimezone(UTC) - current_time.astimezone(UTC)).total_seconds())


class JinaClient:
    async def crawl(self, url: str, return_format: str = "html", timeout: int = 10, proxy: str | None = None, trust_env: bool = True, *, max_retries: int = 0, retry_budget_seconds: float = 30.0) -> str:
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
        retry_budget_exhausted = False
        try:
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
                        retry_after = None
                        last_http_error = None
                        try:
                            response = await client.post("https://r.jina.ai/", headers=headers, json=data, timeout=request_timeout)
                        except (httpx.ConnectError, httpx.ConnectTimeout):
                            if attempt == max_retries:
                                raise
                        else:
                            if response.status_code == 200:
                                if response.text and response.text.strip():
                                    return response.text
                                error_message = "Jina API returned empty response"
                                logger.error(error_message)
                                return f"Error: {error_message}"
                            last_http_error = f"Jina API returned status {response.status_code}: {response.text}"
                            if attempt == max_retries:
                                logger.error(last_http_error)
                                return f"Error: {last_http_error}"
                            if response.status_code == 429:
                                retry_after = _parse_retry_after(response.headers.get("Retry-After"))
                                if retry_after is None:
                                    logger.error(last_http_error)
                                    return f"Error: {last_http_error}"
                            elif response.status_code == 503:
                                retry_after = _parse_retry_after(response.headers.get("Retry-After"))
                            elif response.status_code not in {502, 504}:
                                logger.error(last_http_error)
                                return f"Error: {last_http_error}"

                        # Keep local jitter as a minimum pacing floor. A valid
                        # server hint is never jittered or shortened to fit the
                        # retry budget.
                        local_wait = delay * random.uniform(0.5, 1.0)
                        wait_seconds = max(local_wait, retry_after) if retry_after is not None else local_wait
                        remaining = deadline - asyncio.get_running_loop().time()
                        if remaining <= wait_seconds:
                            if last_http_error is not None:
                                logger.error(last_http_error)
                                return f"Error: {last_http_error}"
                            retry_budget_exhausted = True
                            raise TimeoutError
                        await asyncio.sleep(wait_seconds)
                        delay = min(delay * 2, 4.0)
        except Exception as e:
            if isinstance(e, TimeoutError) and max_retries and (retry_budget_exhausted or asyncio.get_running_loop().time() >= deadline):
                error_message = "Request to Jina API failed: retry time budget exhausted"
            else:
                error_message = f"Request to Jina API failed: {type(e).__name__}: {e}"
            logger.warning(error_message)
            return f"Error: {error_message}"
