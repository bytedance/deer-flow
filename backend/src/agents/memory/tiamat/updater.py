"""TIAMAT-backed memory updater for DeerFlow.

Drop-in replacement for MemoryUpdater that stores updates in TIAMAT's cloud
instead of local memory.json. Uses the same LLM-based extraction pipeline
but persists results to https://memory.tiamat.live.
"""

from typing import Any

from src.agents.memory.prompt import MEMORY_UPDATE_PROMPT, format_conversation_for_update
from src.agents.memory.tiamat.store import TiamatMemoryStore
from src.config.memory_config import get_memory_config
from src.models import create_chat_model

import json


class TiamatMemoryUpdater:
    """Updates memory using LLM and stores results in TIAMAT.

    Compatible with DeerFlow's MemoryUpdater interface but uses TIAMAT's
    cloud API for storage instead of local files.
    """

    def __init__(
        self,
        store: TiamatMemoryStore,
        model_name: str | None = None,
    ):
        """Initialize the TIAMAT memory updater.

        Args:
            store: TiamatMemoryStore instance for persistence.
            model_name: Optional model name for LLM extraction.
        """
        self._store = store
        self._model_name = model_name

    def _get_model(self):
        """Get the model for memory updates."""
        config = get_memory_config()
        model_name = self._model_name or config.model_name
        return create_chat_model(name=model_name, thinking_enabled=False)

    def update_memory(self, messages: list[Any], thread_id: str | None = None) -> bool:
        """Update memory based on conversation messages.

        Args:
            messages: List of conversation messages.
            thread_id: Optional thread ID for tracking source.

        Returns:
            True if update was successful, False otherwise.
        """
        config = get_memory_config()
        if not config.enabled:
            return False

        if not messages:
            return False

        try:
            # Get current memory from TIAMAT
            current_memory = self._store.load_memory()

            # Format conversation for prompt
            conversation_text = format_conversation_for_update(messages)
            if not conversation_text.strip():
                return False

            # Build prompt and call LLM
            prompt = MEMORY_UPDATE_PROMPT.format(
                current_memory=json.dumps(current_memory, indent=2),
                conversation=conversation_text,
            )

            model = self._get_model()
            response = model.invoke(prompt)
            response_text = str(response.content).strip()

            # Parse response (strip markdown code blocks)
            if response_text.startswith("```"):
                lines = response_text.split("\n")
                response_text = "\n".join(
                    lines[1:-1] if lines[-1] == "```" else lines[1:]
                )

            update_data = json.loads(response_text)

            # Apply updates using DeerFlow's standard logic
            from src.agents.memory.updater import MemoryUpdater
            updater = MemoryUpdater()
            updated_memory = updater._apply_updates(
                current_memory, update_data, thread_id
            )

            # Save to TIAMAT instead of local file
            return self._store.save_memory(updated_memory)

        except json.JSONDecodeError as e:
            print(f"[TiamatMemoryUpdater] Failed to parse LLM response: {e}")
            return False
        except Exception as e:
            print(f"[TiamatMemoryUpdater] Update failed: {e}")
            return False
