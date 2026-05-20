"""Persists summarized-away messages to ``{thread_dir}/message_archive.jsonl``."""

from __future__ import annotations

import json
import logging

from langchain_core.messages import AnyMessage

from deerflow.agents.middlewares.summarization_middleware import BeforeSummarizationHook, SummarizationEvent
from deerflow.config.paths import get_paths
from deerflow.runtime.user_context import get_effective_user_id

logger = logging.getLogger(__name__)


class MessageArchiveHook:
    """Writes messages_to_summarize to a per-thread JSONL archive, deduped by message id."""

    def __call__(self, event: SummarizationEvent) -> None:
        if not event.thread_id:
            return
        if not event.messages_to_summarize:
            return
        try:
            self._write(event.thread_id, list(event.messages_to_summarize))
        except Exception:
            logger.exception("MessageArchiveHook: failed to write message archive for thread %s", event.thread_id)

    def _write(self, thread_id: str, messages: list[AnyMessage]) -> None:
        user_id = get_effective_user_id()
        archive_path = get_paths().thread_dir(thread_id, user_id=user_id) / "message_archive.jsonl"
        archive_path.parent.mkdir(parents=True, exist_ok=True)

        existing_ids: set[str] = set()
        if archive_path.exists():
            try:
                with archive_path.open("r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                            msg_id = data.get("id")
                            if msg_id:
                                existing_ids.add(msg_id)
                        except json.JSONDecodeError:
                            logger.debug("MessageArchiveHook: skipping corrupt line in %s", archive_path)
            except OSError:
                logger.debug("MessageArchiveHook: could not read existing archive at %s", archive_path)

        new_lines: list[str] = []
        for msg in messages:
            msg_dict = msg.model_dump()
            msg_id = msg_dict.get("id")
            if msg_id and msg_id in existing_ids:
                continue
            new_lines.append(json.dumps(msg_dict, ensure_ascii=False))
            if msg_id:
                existing_ids.add(msg_id)

        if not new_lines:
            return

        with archive_path.open("a", encoding="utf-8") as f:
            f.write("\n".join(new_lines) + "\n")


message_archive_hook: BeforeSummarizationHook = MessageArchiveHook()
