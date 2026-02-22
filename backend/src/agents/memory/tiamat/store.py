"""TIAMAT-backed memory store for DeerFlow agents.

Replaces the default file-based memory.json with TIAMAT's cloud memory API,
providing persistent, searchable, cross-session memory without local file I/O.

Usage::

    from src.agents.memory.tiamat import TiamatMemoryStore

    store = TiamatMemoryStore(api_key="your-tiamat-api-key")
    store.save_memory(memory_data)
    memory = store.load_memory()
"""

import json
import os
from datetime import datetime
from typing import Any

import httpx


TIAMAT_BASE_URL = "https://memory.tiamat.live"


class TiamatMemoryStore:
    """Cloud memory store backed by TIAMAT's Memory API.

    Drop-in replacement for DeerFlow's file-based memory storage.
    Memories are stored in TIAMAT's cloud with FTS5 full-text search
    and persist across restarts without any local files.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = TIAMAT_BASE_URL,
        agent_id: str = "deer-flow",
    ):
        """Initialize the TIAMAT memory store.

        Args:
            api_key: TIAMAT API key. If None, reads from TIAMAT_API_KEY env var.
            base_url: Base URL for the TIAMAT Memory API.
            agent_id: Identifier for this agent instance (used as tag prefix).
        """
        self._api_key = api_key or os.environ.get("TIAMAT_API_KEY", "")
        self._base_url = base_url.rstrip("/")
        self._agent_id = agent_id
        self._client = httpx.Client(
            base_url=self._base_url,
            headers={"X-API-Key": self._api_key, "Content-Type": "application/json"},
            timeout=30.0,
        )

    @classmethod
    def register_and_create(
        cls,
        agent_name: str = "deer-flow",
        purpose: str = "DeerFlow agent memory",
        base_url: str = TIAMAT_BASE_URL,
    ) -> "TiamatMemoryStore":
        """Create a store with auto-registered API key.

        Args:
            agent_name: Name to register the API key under.
            purpose: Purpose description for the API key.
            base_url: Base URL for the TIAMAT Memory API.

        Returns:
            A configured TiamatMemoryStore with a fresh API key.
        """
        resp = httpx.post(
            f"{base_url}/api/keys/register",
            json={"agent_name": agent_name, "purpose": purpose},
            timeout=30.0,
        )
        resp.raise_for_status()
        api_key = resp.json()["api_key"]
        return cls(api_key=api_key, base_url=base_url, agent_id=agent_name)

    def save_memory(self, memory_data: dict[str, Any]) -> bool:
        """Save the full memory state to TIAMAT.

        Args:
            memory_data: DeerFlow memory dict (user context, history, facts).

        Returns:
            True if saved successfully.
        """
        try:
            # Store the full memory state as a single tagged memory
            resp = self._client.post(
                "/api/memory/store",
                json={
                    "content": json.dumps(memory_data, ensure_ascii=False),
                    "tags": [f"agent:{self._agent_id}", "memory_state", "latest"],
                    "importance": 1.0,
                },
            )
            resp.raise_for_status()

            # Also store individual facts for searchability
            for fact in memory_data.get("facts", []):
                self._client.post(
                    "/api/memory/store",
                    json={
                        "content": fact.get("content", ""),
                        "tags": [
                            f"agent:{self._agent_id}",
                            "fact",
                            fact.get("category", "context"),
                        ],
                        "importance": fact.get("confidence", 0.5),
                    },
                )

            return True
        except Exception as e:
            print(f"[TiamatMemoryStore] Failed to save: {e}")
            return False

    def load_memory(self) -> dict[str, Any]:
        """Load memory state from TIAMAT.

        Returns:
            DeerFlow memory dict, or empty memory structure if none found.
        """
        try:
            resp = self._client.post(
                "/api/memory/recall",
                json={
                    "query": f"agent:{self._agent_id} memory_state",
                    "limit": 1,
                },
            )
            if resp.status_code != 200:
                return self._empty_memory()

            memories = resp.json().get("memories", [])
            if not memories:
                return self._empty_memory()

            content = memories[0].get("content", "{}")
            return json.loads(content)
        except Exception as e:
            print(f"[TiamatMemoryStore] Failed to load: {e}")
            return self._empty_memory()

    def search_facts(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search stored facts using TIAMAT's FTS5 full-text search.

        This is a capability that file-based storage doesn't have — semantic
        search across all stored agent memories.

        Args:
            query: Search query string.
            limit: Maximum number of results.

        Returns:
            List of matching fact dicts.
        """
        try:
            resp = self._client.post(
                "/api/memory/recall",
                json={"query": query, "limit": limit},
            )
            if resp.status_code != 200:
                return []

            memories = resp.json().get("memories", [])
            return [
                {"content": m.get("content", ""), "tags": m.get("tags", [])}
                for m in memories
            ]
        except Exception:
            return []

    def store_knowledge(
        self,
        subject: str,
        predicate: str,
        obj: str,
        confidence: float = 1.0,
    ) -> bool:
        """Store a knowledge triple in TIAMAT.

        Enables structured knowledge storage beyond what DeerFlow's
        flat fact list supports.

        Args:
            subject: The subject entity.
            predicate: The relationship.
            obj: The object entity.
            confidence: Confidence score (0.0 - 1.0).

        Returns:
            True if stored successfully.
        """
        try:
            resp = self._client.post(
                "/api/memory/learn",
                json={
                    "subject": subject,
                    "predicate": predicate,
                    "object": obj,
                    "confidence": confidence,
                },
            )
            return resp.status_code == 200
        except Exception:
            return False

    def get_stats(self) -> dict[str, Any]:
        """Get usage statistics from TIAMAT.

        Returns:
            Dict with memory count, recall usage, etc.
        """
        try:
            resp = self._client.get("/api/memory/stats")
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass
        return {}

    def _empty_memory(self) -> dict[str, Any]:
        """Create an empty DeerFlow-compatible memory structure."""
        return {
            "version": "1.0",
            "lastUpdated": datetime.utcnow().isoformat() + "Z",
            "user": {
                "workContext": {"summary": "", "updatedAt": ""},
                "personalContext": {"summary": "", "updatedAt": ""},
                "topOfMind": {"summary": "", "updatedAt": ""},
            },
            "history": {
                "recentMonths": {"summary": "", "updatedAt": ""},
                "earlierContext": {"summary": "", "updatedAt": ""},
                "longTermBackground": {"summary": "", "updatedAt": ""},
            },
            "facts": [],
        }

    def close(self) -> None:
        """Close the HTTP client."""
        self._client.close()
