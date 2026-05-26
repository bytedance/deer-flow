"""Dify HTTP client for chatflow apps."""

import logging

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class DifyAPIError(Exception):
    """Raised when Dify API returns a non-2xx response."""

    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"Dify API error {status_code}: {message}")


class DifyResponse(BaseModel):
    answer: str
    conversation_id: str
    message_id: str


class DifyClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = "http://localhost:8000",
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    def chat(
        self,
        query: str,
        conversation_id: str,
        user: str,
        timeout: float = 60.0,
    ) -> DifyResponse:
        """Send a chat message to the Dify chatflow."""
        url = f"{self.base_url}/v1/chat-messages"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "inputs": {},
            "query": query,
            "response_mode": "blocking",
            "conversation_id": conversation_id,
            "user": user,
            "files": [],
        }

        try:
            response = httpx.post(url, json=payload, headers=headers, timeout=timeout)
        except httpx.TimeoutException:
            raise DifyAPIError(0, "Request to Dify timed out")

        if not response.is_success:
            try:
                error_body = response.json()
                message = error_body.get("message", response.text)
            except httpx.HTTPError:
                message = response.text or "Unknown error"
            raise DifyAPIError(response.status_code, message)

        data = response.json()
        if "answer" not in data:
            raise DifyAPIError(response.status_code, "Dify response missing 'answer' field")
        return DifyResponse(
            answer=data.get("answer", ""),
            conversation_id=data.get("conversation_id", ""),
            message_id=data.get("message_id", ""),
        )
