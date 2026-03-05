from __future__ import annotations

import importlib
import logging
import os
import threading
from concurrent.futures import TimeoutError
from dataclasses import dataclass
from collections.abc import Callable
from typing import Any

from src.config.title_config import TitleConfig, get_title_config
from src.models import create_chat_model

logger = logging.getLogger(__name__)

DEFAULT_LANGGRAPH_URL = "http://localhost:2024"


def _load_sync_client() -> Callable[..., Any] | None:
    try:
        module = importlib.import_module("langgraph_sdk")
        return getattr(module, "get_sync_client", None)
    except Exception:
        return None


_get_sync_client = _load_sync_client()


@dataclass
class TitleGenerationTask:
    thread_id: str
    messages: list[Any]


class TitleGenerationUpdater:
    def __init__(self, langgraph_url: str | None = None, client_factory: Callable[[str], Any] | None = None):
        self._langgraph_url = langgraph_url or self._resolve_langgraph_url()
        self._client_factory = client_factory

    def process(self, task: TitleGenerationTask) -> None:
        # Avoid unnecessary title generation if the thread already has a non-default/manual title.
        if self._has_non_default_title(task.thread_id):
            return

        title = self.generate_title(task.messages)
        self._update_thread_title_if_needed(task.thread_id, title)

    def _has_non_default_title(self, thread_id: str) -> bool:
        """
        Returns True if the thread already has a non-empty title, indicating that
        a manual or non-default title has been set and we should skip generation.
        """
        # If no client is available, we cannot check the existing title; fall back to generation.
        if self._client_factory is None and _get_sync_client is None:
            return False

        try:
            if self._client_factory is not None:
                client = self._client_factory(self._langgraph_url)
            else:
                client = _get_sync_client(self._langgraph_url)  # type: ignore[misc]

            thread = client.threads.get(thread_id)
        except Exception as exc:
            logger.warning("Failed to fetch thread %s while checking existing title: %s", thread_id, exc)
            return False

        existing_title = getattr(thread, "title", None)
        if not isinstance(existing_title, str):
            return False

        return existing_title.strip() != ""
    def generate_title(self, messages: list[Any]) -> str:
        config = get_title_config()
        user_msg, assistant_msg = self._extract_messages(messages)
        prompt = config.prompt_template.format(
            max_words=config.max_words,
            user_msg=user_msg[:500],
            assistant_msg=assistant_msg[:500],
        )

        for attempt in range(config.max_retries + 1):
            try:
                return self._invoke_with_timeout(prompt=prompt, config=config)
            except TimeoutError:
                logger.warning(
                    "Title generation timed out (attempt %s/%s)",
                    attempt + 1,
                    config.max_retries + 1,
                )
            except Exception as e:
                logger.warning(
                    "Title generation failed (attempt %s/%s): %s",
                    attempt + 1,
                    config.max_retries + 1,
                    e,
                )

        return self._fallback_title(user_msg, config)

    def _invoke_with_timeout(self, prompt: str, config: TitleConfig) -> str:
        result: dict[str, Any] = {}
        error: dict[str, BaseException] = {}

        def _invoke() -> None:
            try:
                model = create_chat_model(name=config.model_name, thinking_enabled=False)
                response = model.invoke(prompt)
                result["content"] = str(getattr(response, "content", "") or "")
            except Exception as exc:
                error["exception"] = exc

        worker = threading.Thread(target=_invoke, daemon=True)
        worker.start()
        worker.join(timeout=config.timeout_seconds)
        if worker.is_alive():
            raise TimeoutError("title generation timed out")
        if "exception" in error:
            raise error["exception"]

        normalized = self._normalize_title(str(result.get("content", "")), config)
        if not normalized:
            raise ValueError("empty title generated")
        return normalized

    def _update_thread_title_if_needed(self, thread_id: str, title: str) -> None:
        if not title:
            return

        client = None
        try:
            client = self._create_client(self._langgraph_url)
            if client is None:
                logger.warning("langgraph_sdk is not available, skipping async title write-back")
                return

            state = client.threads.get_state(thread_id)
            current_title = self._normalize_existing_title(state)
            if current_title and current_title != "Untitled":
                logger.info(
                    "Skip title write-back for thread %s: title already set to '%s'",
                    thread_id,
                    current_title,
                )
                return

            client.threads.update_state(
                thread_id,
                values={"title": title},
                checkpoint=state.get("checkpoint"),
                as_node="title_middleware",
            )
            logger.info("Async title updated for thread %s: %s", thread_id, title)
        except Exception as e:
            logger.error("Failed to write async title for thread %s: %s", thread_id, e)
        finally:
            if client is not None and hasattr(client, "close"):
                client.close()

    def _create_client(self, url: str):
        if self._client_factory is not None:
            return self._client_factory(url)
        if _get_sync_client is None:
            return None
        return _get_sync_client(url=url, api_key=None)

    def _resolve_langgraph_url(self) -> str:
        return (
            os.getenv("DEER_FLOW_LANGGRAPH_URL")
            or os.getenv("LANGGRAPH_API_URL")
            or os.getenv("LANGGRAPH_URL")
            or DEFAULT_LANGGRAPH_URL
        )

    def _extract_messages(self, messages: list[Any]) -> tuple[str, str]:
        user_msg_content = next((m.content for m in messages if getattr(m, "type", None) == "human"), "")
        assistant_msg_content = next((m.content for m in messages if getattr(m, "type", None) == "ai"), "")
        return (str(user_msg_content) if user_msg_content else "", str(assistant_msg_content) if assistant_msg_content else "")

    def _normalize_title(self, raw_title: str, config: TitleConfig) -> str:
        title = raw_title.strip().strip('"').strip("'")
        return title[: config.max_chars] if len(title) > config.max_chars else title

    def _fallback_title(self, user_msg: str, config: TitleConfig) -> str:
        fallback_chars = min(config.max_chars, 50)
        if len(user_msg) > fallback_chars:
            return user_msg[:fallback_chars].rstrip() + "..."
        return user_msg if user_msg else "New Conversation"

    def _normalize_existing_title(self, state: dict[str, Any]) -> str:
        values = state.get("values") or {}
        return str(values.get("title") or "").strip()
