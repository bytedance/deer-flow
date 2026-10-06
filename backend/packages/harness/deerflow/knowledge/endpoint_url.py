"""Joining a leg's fixed path onto a user-supplied endpoint (spec 2026-09-26 rag-endpoint-dedup).

Providers' docs give bases that already carry ``/v1`` (OpenAI SDK, Ollama, SiliconFlow,
DashScope's compatible surface, Jina), while the two generic legs' own fixed paths start
with ``/v1`` as well — this joins without doubling that segment, and keeps a whole-endpoint
address as it is. Vendor legs (host + proprietary whole-segment paths) do not use this.

No empty-address guard lives here: every caller runs behind the required-address checks
(spec 2026-09-25 rag-endpoint-unlock).
"""


def join_endpoint(base_url: str, path: str) -> str:
    """Join ``path`` onto ``base_url``; a segment the two share is never written twice."""
    base = (base_url or "").strip().rstrip("/")
    # Ecosystem base (`…/v1`) + a path that starts with `/v1/`: skip the duplicate segment.
    if path.startswith("/v1/") and base.endswith("/v1"):
        path = path[len("/v1") :]
    # A whole endpoint (`…/v1/embeddings`, `…/rerank`) stays as it is.
    if base.endswith(path):
        return base
    return base + path
