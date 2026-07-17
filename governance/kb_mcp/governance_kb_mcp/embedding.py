import logging
import httpx
from governance_kb_mcp.config import KBConfig

logger = logging.getLogger(__name__)


class EmbeddingClient:
    def __init__(self, config: KBConfig):
        self._config = config

    def embed(self, text: str) -> list[float]:
        if not self._config.volcengine_api_key:
            logger.warning("VOLCENGINE_API_KEY not set, embedding skipped")
            return []
        try:
            with httpx.Client(timeout=self._config.embedding_timeout) as client:
                resp = client.post(
                    f"{self._config.embedding_api_base}/embeddings",
                    headers={
                        "Authorization": f"Bearer {self._config.volcengine_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self._config.embedding_model,
                        "input": text,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                return data["data"][0]["embedding"]
        except httpx.TimeoutException:
            logger.warning("Embedding API timed out, returning empty vector")
            return []
        except Exception as e:
            logger.warning("Embedding API error: %s", e)
            return []

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not self._config.volcengine_api_key:
            logger.warning("VOLCENGINE_API_KEY not set, embedding skipped")
            return [[] for _ in texts]
        try:
            with httpx.Client(timeout=self._config.embedding_timeout) as client:
                resp = client.post(
                    f"{self._config.embedding_api_base}/embeddings",
                    headers={
                        "Authorization": f"Bearer {self._config.volcengine_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self._config.embedding_model,
                        "input": texts,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                return [item["embedding"] for item in data["data"]]
        except httpx.TimeoutException:
            logger.warning("Embedding API timed out, returning empty vectors")
            return [[] for _ in texts]
        except Exception as e:
            logger.warning("Embedding API error: %s", e)
            return [[] for _ in texts]
