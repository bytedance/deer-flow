"""Dify HTTP client for chatflow apps."""

import logging
from pathlib import Path

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# File handler: write to backend/logs/dify.log (sibling to backend/app/)
_backend_dir = Path(__file__).resolve().parent.parent.parent.parent
_logs_dir = _backend_dir / "logs"
_logs_dir.mkdir(parents=True, exist_ok=True)
_file_handler = logging.FileHandler(_logs_dir / "dify.log", mode="a", encoding="utf-8")
_file_handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
_file_handler.setLevel(logging.DEBUG)
logger.addHandler(_file_handler)
logger.setLevel(logging.DEBUG)


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
        logger.debug("DifyClient initialized with base_url=%s", self.base_url)

    def chat(
        self,
        query: str,
        conversation_id: str,
        user: str,
        timeout: float = 60.0,
    ) -> DifyResponse:
        """Send a chat message to the Dify chatflow."""
        logger.info("Dify chat request: query=%r, conversation_id=%r, user=%r", query, conversation_id, user)
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
            logger.error("Dify request timed out (url=%s, timeout=%.1fs)", url, timeout)
            raise DifyAPIError(0, "Request to Dify timed out")

        if not response.is_success:
            try:
                error_body = response.json()
                message = error_body.get("message", response.text)
            except httpx.HTTPError:
                message = response.text or "Unknown error"
            logger.error("Dify API error: status=%d, message=%s", response.status_code, message)
            raise DifyAPIError(response.status_code, message)

        data = response.json()
        if "answer" not in data:
            logger.error("Dify response missing 'answer' field: %s", data)
            raise DifyAPIError(response.status_code, "Dify response missing 'answer' field")
        result = DifyResponse(
            answer=data.get("answer", ""),
            conversation_id=data.get("conversation_id", ""),
            message_id=data.get("message_id", ""),
        )
        logger.info("Dify chat response: answer=%r, conversation_id=%r, message_id=%r", result.answer[:50] if result.answer else "", result.conversation_id, result.message_id)
        return result

    def chat_stream(
        self,
        query: str,
        conversation_id: str,
        user: str,
        timeout: float = 60.0,
    ) -> tuple[list[str], str]:
        """Streaming mode: parse SSE lines, return (chunks, conversation_id).

        Dify streaming API returns SSE lines:
            event: message
            data: {"answer": "...", "conversation_id": "...", "message_id": "..."}

        Returns:
            tuple: (chunks: list[str], conversation_id: str)
                chunks — all answer fragments in order
                conversation_id — last non-empty conversation_id from the stream
        """
        import json

        logger.debug("Dify streaming request: query=%r, conversation_id=%r, user=%r", query, conversation_id, user)
        url = f"{self.base_url}/v1/chat-messages"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "inputs": {},
            "query": query,
            "response_mode": "streaming",
            "conversation_id": conversation_id,
            "user": user,
            "files": [],
        }

        try:
            response = httpx.post(url, json=payload, headers=headers, timeout=timeout)
        except httpx.TimeoutException:
            logger.error("Dify streaming request timed out (url=%s)", url)
            raise DifyAPIError(0, "Request to Dify timed out")

        if not response.is_success:
            try:
                error_body = response.json()
                message = error_body.get("message", response.text)
            except httpx.HTTPError:
                message = response.text or "Unknown error"
            logger.error("Dify streaming API error: status=%d, message=%s", response.status_code, message)
            raise DifyAPIError(response.status_code, message)

        current_event = None
        conversation_id_result = [""]
        chunks = []

        for line in response.iter_lines():
            if line.startswith(b"event: "):
                current_event = line.decode("utf-8")[7:].strip()
                continue
            if not line.startswith(b"data: ") or current_event != "message":
                continue
            data_str = line.decode("utf-8")[6:].strip()
            if not data_str:
                continue
            try:
                data = json.loads(data_str)
            except json.JSONDecodeError:
                continue
            answer = data.get("answer", "")
            if answer:
                chunks.append(answer)
            if data.get("conversation_id"):
                conversation_id_result[0] = data["conversation_id"]

        logger.info("Dify streaming completed: chunks=%d, conversation_id=%s", len(chunks), conversation_id_result[0])
        return chunks, conversation_id_result[0]
