import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class BrowserlessClient:
    """Client for Browserless headless Chrome API."""

    def __init__(self, base_url: str, token: str = "", timeout_s: float = 30) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout_s = timeout_s

    def fetch_html(
        self,
        url: str,
        wait_until: str = "networkidle2",
        goto_timeout_ms: int = 30000,
        wait_for_timeout_ms: int = 0,
        wait_for_selector: str = "",
        wait_for_selector_timeout_ms: int = 5000,
        best_attempt: bool = True,
        reject_resource_types: list[str] | None = None,
        reject_request_pattern: list[str] | None = None,
    ) -> str:
        """Fetch the rendered HTML of a page using Browserless.

        Args:
            url: The URL to fetch.
            wait_until: When to consider navigation complete.
            goto_timeout_ms: Navigation timeout in milliseconds.
            wait_for_timeout_ms: Extra wait after page load.
            wait_for_selector: CSS selector to wait for.
            wait_for_selector_timeout_ms: Timeout for selector wait.
            best_attempt: Whether to attempt multiple strategies.
            reject_resource_types: Resource types to block.
            reject_request_pattern: URL patterns to block.

        Returns:
            Rendered HTML content.
        """
        payload: dict[str, Any] = {
            "url": url,
            "waitUntil": wait_until,
            "gotoTimeout": goto_timeout_ms,
            "bestAttempt": best_attempt,
        }

        if self.token:
            payload["token"] = self.token
        if wait_for_timeout_ms > 0:
            payload["waitForTimeout"] = wait_for_timeout_ms
        if wait_for_selector:
            payload["waitForSelector"] = {
                "selector": wait_for_selector,
                "timeout": wait_for_selector_timeout_ms,
            }
        if reject_resource_types:
            payload["rejectResourceTypes"] = reject_resource_types
        if reject_request_pattern:
            payload["rejectRequestPattern"] = reject_request_pattern

        logger.debug(f"Fetching URL via Browserless: {url}")
        try:
            with httpx.Client(timeout=self.timeout_s) as client:
                resp = client.post(
                    f"{self.base_url}/content",
                    json=payload,
                    headers={
                        "Content-Type": "application/json",
                        "Cache-Control": "no-cache",
                    },
                )

                code = resp.status_code
                target_code = resp.headers.get("X-Response-Code", "")
                target_status = resp.headers.get("X-Response-Status", "")
                target_url = resp.headers.get("X-Response-URL", "")

                logger.debug(
                    f"Browserless response: code={code}, "
                    f"target_code={target_code}, target_status={target_status}"
                )

                if code != 200:
                    return (
                        f"Error: Browserless HTTP {code}: {resp.text[:200]}"
                    )

                html = resp.text
                if not html or not html.strip():
                    return "Error: Browserless returned empty response"

                return html

        except httpx.TimeoutException:
            return f"Error: Browserless request timed out after {self.timeout_s}s"
        except httpx.RequestError as e:
            logger.error(f"Browserless request failed: {e}")
            return f"Error: Browserless request failed: {e!s}"
        except Exception as e:
            logger.error(f"Browserless fetch failed: {e}")
            return f"Error: Browserless fetch failed: {e!s}"
