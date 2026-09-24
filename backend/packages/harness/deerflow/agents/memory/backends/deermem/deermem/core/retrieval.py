"""FTS5-based retrieval engine for DeerMem.

Provides BM25 full-text search over stored facts with:
- jieba Chinese tokenization (optional, falls back to whitespace)
- FTS5 MATCH syntax support (AND/OR/NOT/phrase/prefix) with fallback
- Time-decay + confidence-weighted ranking
- Category filtering
- Scope (user_id) isolation

``FTS5Retrieval`` is the low-level SQLite engine.  The storage integration is
owned by ``FTS5RetrievalAdapter``, which implements ``storage.RetrievalPort``
without importing storage and creating a circular dependency.
"""

from __future__ import annotations

import json
import logging
import math
import re
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Scoring weights ──────────────────────────────────────────────────
#
# SQLite FTS5 ``bm25(memory_fts)`` (no positional params → defaults K1=1.2,
# B=0.75) returns a negative value whose magnitude scales with document
# relevance.  Critically the function takes positional params in order
# ``(table, k1, b, *column_weights)``: the original code passed
# ``bm25(..., 0.0, 0.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0)``, which set **k1 = 0**
# and silently zeroed out the entire BM25 score (disabled tf saturation),
# collapsing ranking to ``confidence * _CONFIDENCE_WEIGHT``.  Use the
# no-arg form so SQLite defaults apply and BM25 is actually scored.
_CONFIDENCE_WEIGHT = 0.2


# ── jieba (optional) ──────────────────────────────────────────────────

try:
    import jieba

    _jieba_available = True
except ImportError:
    _jieba_available = False


def _tokenize(text: str) -> list[str]:
    """Tokenize text: jieba for Chinese, whitespace split for English."""
    if not text or not text.strip():
        return []
    if _jieba_available:
        return [t for t in jieba.cut(text) if t.strip()]
    return [t for t in text.split() if t.strip()]


# ── FTS5 query preprocessing ──────────────────────────────────────────

_FTS5_ADVANCED_RE = re.compile(
    r"(\bAND\b|\bOR\b|\bNOT\b|\bNEAR\b"
    r'|"\w.*?"'  # phrase "..."
    r"|\w+\*"  # prefix prefix*
    r"|\(.*?\))"  # group (...)
)


def _is_advanced_query(query: str) -> bool:
    """Detect whether the query uses FTS5 advanced syntax."""
    return bool(_FTS5_ADVANCED_RE.search(query))


def _build_fallback_query(query: str) -> str:
    """Convert natural-language query to FTS5 OR query (fallback strategy)."""
    tokens = [token for token in _tokenize(query) if any(char.isalnum() for char in token)]
    if not tokens:
        return ""
    # Quote each token so punctuation in natural-language input cannot become
    # an FTS5 operator or syntax error. Double quotes inside a token are the
    # FTS5 escape sequence for a literal quote.
    return " OR ".join(f'"{token.replace(chr(34), chr(34) * 2)}"' for token in tokens)


# ── Core retrieval engine ─────────────────────────────────────────────


class FTS5Retrieval:
    """SQLite FTS5-based retrieval engine.

    Query strategy:
      1. Advanced FTS5 syntax -> pass through to MATCH
      2. Natural language -> jieba tokenize + OR join
      3. Syntax error -> fall back to tokenized OR query
      4. Still fails -> return empty

    Ranking:
      BM25 score × time_decay + confidence × 0.2
    """

    def __init__(self, db_path: str | Path = ":memory:"):
        self._db_path = str(db_path)
        # Gateway runs tool calls via asyncio.to_thread / ThreadPoolExecutor;
        # SQLite connections are not safe to share across threads even when the
        # top-level instance is single-process. We pick two defensive layers:
        #   1. ``check_same_thread=False`` so a connection created in thread A
        #      is accessible from thread B (libsqlite itself is reentrant under
        #      a serialised wrapper, see #4208 hot-path discussion).
        #   2. ``_lock`` guards all mutating sqlite calls so concurrent callers
        #      serialise through here (prevents interleaved writes / FTS5 index
        #      reorderings). Callers from outside instance methods MUST enter
        #      the lock via the public API and not bypass into ``self._conn``.
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._lock = threading.RLock()
        try:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA busy_timeout=30000")
            self._init_schema()
        except Exception:
            self._conn.close()
            raise

    def _init_schema(self) -> None:
        conn = self._conn
        conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
                doc_id UNINDEXED,
                content,
                raw_content UNINDEXED,
                category UNINDEXED,
                scope_user UNINDEXED,
                scope_agent UNINDEXED,
                created_at UNINDEXED,
                confidence UNINDEXED,
                source UNINDEXED,
                fact_json UNINDEXED,
                tokenize='unicode61'
            )
            """
        )
        conn.commit()

    # ── Index operations ───────────────────────────────────────────────

    def _preprocess_content(self, content: str) -> str:
        """Preprocess content for indexing: jieba tokenize for Chinese."""
        if not content:
            return ""
        if _jieba_available:
            tokens = _tokenize(content)
            return " ".join(tokens)
        return content

    def _row_from_document(self, document: dict[str, Any]) -> tuple[Any, ...]:
        now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        return (
            document["fact_id"],
            self._preprocess_content(document["content"]),
            document["content"],
            document["category"],
            document["scope_user"],
            document["scope_agent"],
            document.get("created_at") or now,
            document.get("confidence", 0.5),
            document.get("source"),
            json.dumps(document.get("fact_data"), ensure_ascii=False, default=str),
        )

    def index_fact(
        self,
        fact_id: str,
        content: str,
        category: str = "context",
        confidence: float = 0.5,
        created_at: str | None = None,
        scope_user: str | None = None,
        scope_agent: str | None = None,
        source: str | None = None,
        fact_data: dict[str, Any] | None = None,
    ) -> None:
        """Insert or update a fact in the FTS5 index."""
        with self._lock:
            conn = self._conn
            # Delete existing entry with same doc_id (INSERT OR REPLACE for FTS5)
            conn.execute("DELETE FROM memory_fts WHERE doc_id = ?", (fact_id,))
            conn.execute(
                """
                INSERT INTO memory_fts(
                    doc_id, content, raw_content, category, scope_user, scope_agent,
                    created_at, confidence, source, fact_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._row_from_document(
                    {
                        "fact_id": fact_id,
                        "content": content,
                        "category": category,
                        "scope_user": scope_user or "",
                        "scope_agent": scope_agent or "",
                        "created_at": created_at,
                        "confidence": confidence,
                        "source": source,
                        "fact_data": fact_data,
                    }
                ),
            )
            conn.commit()

    def replace_documents(self, documents: list[dict[str, Any]], *, scopes: list[tuple[str, str]] | None = None) -> None:
        """Atomically replace all or selected scope rows in one transaction."""
        with self._lock:
            conn = self._conn
            try:
                conn.execute("BEGIN IMMEDIATE")
                if scopes is None:
                    conn.execute("DELETE FROM memory_fts")
                else:
                    conn.executemany(
                        "DELETE FROM memory_fts WHERE scope_user = ? AND scope_agent = ?",
                        scopes,
                    )
                conn.executemany(
                    """
                    INSERT INTO memory_fts(
                        doc_id, content, raw_content, category, scope_user, scope_agent,
                        created_at, confidence, source, fact_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [self._row_from_document(document) for document in documents],
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def remove_fact(self, fact_id: str) -> None:
        """Remove a fact from the FTS5 index."""
        with self._lock:
            conn = self._conn
            conn.execute("DELETE FROM memory_fts WHERE doc_id = ?", (fact_id,))
            conn.commit()

    def clear_index(self) -> None:
        """Clear the entire FTS5 index."""
        with self._lock:
            conn = self._conn
            conn.execute("DELETE FROM memory_fts")
            conn.commit()

    def clear_scope(self, *, scope_user: str, scope_agent: str) -> None:
        """Clear one exact adapter scope without affecting other users."""
        with self._lock:
            self._conn.execute(
                "DELETE FROM memory_fts WHERE scope_user = ? AND scope_agent = ?",
                (scope_user, scope_agent),
            )
            self._conn.commit()

    def rebuild_from_facts(
        self,
        facts: list[dict[str, Any]],
        *,
        scope_user: str | None = None,
        scope_agent: str | None = None,
    ) -> None:
        """Rebuild the entire index from a list of fact dicts."""
        with self._lock:
            conn = self._conn
            try:
                conn.execute("BEGIN")
                conn.execute("DELETE FROM memory_fts")
                for fact in facts:
                    fact_id = fact.get("id", "")
                    content = fact.get("content", "")
                    if not fact_id or not isinstance(content, str) or not content:
                        continue
                    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
                    conn.execute(
                        """
                        INSERT INTO memory_fts(
                            doc_id, content, raw_content, category, scope_user, scope_agent,
                            created_at, confidence, source, fact_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            fact_id,
                            self._preprocess_content(content),
                            content,
                            fact.get("category", "context"),
                            scope_user or "",
                            scope_agent or "",
                            fact.get("createdAt") or now,
                            fact.get("confidence", 0.5),
                            fact.get("source"),
                            json.dumps(fact, ensure_ascii=False, default=str),
                        ),
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    # ── Search ─────────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        *,
        scope_user: str | None = None,
        scope_agent: str | None = None,
        category: str | None = None,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """FTS5 BM25 search with category and scope filtering.

        Returns list of fact dicts (id, content, category, confidence,
        createdAt, source, score, bm25_score) sorted by relevance.
        """
        import time

        _t0 = time.perf_counter()
        if not query or not query.strip() or top_k <= 0:
            logger.debug("FTS5Retrieval.search: skipped (empty/invalid) query=%r top_k=%d", query, top_k)
            return []

        query = query.strip()

        # Determine query strategy
        if _is_advanced_query(query):
            fts5_query = query
            strategy = "advanced"
        else:
            fts5_query = _build_fallback_query(query)
            strategy = "tokenized"
        logger.debug(
            "FTS5Retrieval.search: query=%r strategy=%r fts5_query=%r scope_user=%r scope_agent=%r category=%r top_k=%d",
            query,
            strategy,
            fts5_query,
            scope_user,
            scope_agent,
            category,
            top_k,
        )

        # Try search
        results = self._execute_search(fts5_query, scope_user, scope_agent, category, top_k)
        if results is not None:
            logger.debug(
                "FTS5Retrieval.search: strategy=%r returned %d results in %.1fms",
                strategy,
                len(results),
                (time.perf_counter() - _t0) * 1000,
            )
            return results

        # Fallback: advanced syntax error -> tokenized OR
        if strategy == "advanced":
            fallback = _build_fallback_query(query)
            if fallback and fallback != fts5_query:
                logger.debug("FTS5Retrieval.search: advanced syntax failed, retrying with tokenized fts5_query=%r", fallback)
                results = self._execute_search(fallback, scope_user, scope_agent, category, top_k)
                if results is not None:
                    logger.debug(
                        "FTS5Retrieval.search: tokenized fallback returned %d results in %.1fms",
                        len(results),
                        (time.perf_counter() - _t0) * 1000,
                    )
                    return results

        logger.debug(
            "FTS5Retrieval.search: returning [] (no path produced results) in %.1fms",
            (time.perf_counter() - _t0) * 1000,
        )
        return []

    def _execute_search(
        self,
        fts5_query: str,
        scope_user: str | None,
        scope_agent: str | None,
        category: str | None,
        top_k: int,
    ) -> list[dict[str, Any]] | None:
        """Execute FTS5 query. Return None on syntax error."""
        if not fts5_query:
            return []

        conditions = ["memory_fts MATCH ?"]
        params: list[Any] = [fts5_query]

        if scope_user:
            conditions.append("scope_user = ?")
            params.append(scope_user)
        if scope_agent:
            conditions.append("scope_agent = ?")
            params.append(scope_agent)
        if category:
            conditions.append("category = ?")
            params.append(category)

        where_clause = " AND ".join(conditions)

        sql = f"""
            SELECT doc_id, content, raw_content, category, scope_user, scope_agent,
                   created_at, confidence, source, fact_json,
                   bm25(memory_fts) AS bm25_score
            FROM memory_fts
            WHERE {where_clause}
            ORDER BY bm25_score
            LIMIT ?
        """
        params.append(top_k * 2)

        with self._lock:
            try:
                conn = self._conn
                rows = conn.execute(sql, params).fetchall()
            except sqlite3.OperationalError as e:
                logger.debug("FTS5 query syntax error: %s (query: %s)", e, fts5_query)
                return None

        results: list[dict[str, Any]] = []
        for row in rows:
            (
                doc_id,
                indexed_content,
                raw_content,
                cat,
                s_user,
                s_agent,
                created_at,
                confidence,
                source,
                fact_json,
                bm25_score,
            ) = row

            score = self._compute_final_score(
                bm25_score=-bm25_score,  # FTS5 returns negative
                confidence=confidence,
                created_at=created_at,
            )

            fact: dict[str, Any] = {}
            if fact_json:
                try:
                    decoded = json.loads(fact_json)
                    if isinstance(decoded, dict):
                        fact = decoded
                except (TypeError, ValueError):
                    logger.debug("FTS5 fact metadata was not valid JSON for doc_id=%r", doc_id)
            fact.setdefault("id", doc_id)
            fact.setdefault("content", raw_content if raw_content is not None else indexed_content)
            fact.setdefault("category", cat)
            fact.setdefault("confidence", confidence)
            fact.setdefault("createdAt", created_at)
            fact.setdefault("source", source if source is not None else "fts5")
            fact["score"] = score
            fact["bm25_score"] = -bm25_score
            results.append(fact)

        logger.debug(
            "FTS5 raw SQL: fts5_query=%r scope_user=%r scope_agent=%r category=%r -> %d rows. bm25 raw: %s",
            fts5_query,
            scope_user,
            scope_agent,
            category,
            len(rows),
            [(r["id"], r["bm25_score"]) for r in results[:10]],
        )

        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:top_k]

    def _compute_final_score(
        self,
        bm25_score: float,
        confidence: float,
        created_at: str,
    ) -> float:
        """Combined score: BM25 × time_decay + confidence weight.

        ``bm25_score`` is negative for relevant docs (SQLite FTS5 convention).
        The caller negates it (``-bm25_score``) before storing in the result
        dict, so here we treat it as positive relevance magnitude.
        """
        score = bm25_score

        try:
            dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            age_days = (datetime.now(UTC) - dt).days
            time_decay = 1.0 if age_days < 30 else math.exp(-0.01 * (age_days - 30))
            score *= time_decay
        except (AttributeError, ValueError, TypeError):
            time_decay = -1.0  # sentinel for "unparseable" → skipped decay
            age_days = -1

        try:
            normalized_confidence = float(confidence)
            if not math.isfinite(normalized_confidence):
                raise ValueError
        except (TypeError, ValueError):
            normalized_confidence = 0.5
        score += normalized_confidence * _CONFIDENCE_WEIGHT

        logger.debug(
            "_compute_final_score: bm25_in=%.4f time_decay=%s age_days=%s conf=%.2f -> final=%.4f",
            bm25_score,
            time_decay,
            age_days,
            normalized_confidence,
            score,
        )
        return score

    # ── Stats ──────────────────────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        """Index statistics."""
        with self._lock:
            conn = self._conn
            total = conn.execute("SELECT COUNT(*) FROM memory_fts").fetchone()[0]
        return {
            "total_docs": total,
            "jieba": _jieba_available,
            "db_path": self._db_path,
        }

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def _scope_value(value: str | None) -> str:
    """Encode a typed scope value so ``None`` cannot collide with a user id."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _scope_key(scope: dict[str, str | None]) -> tuple[str, str]:
    user_id = scope.get("userId")
    agent_name = scope.get("agentName")
    if user_id is not None and not isinstance(user_id, str):
        raise ValueError("retrieval scope userId must be a string or null")
    if agent_name is not None and not isinstance(agent_name, str):
        raise ValueError("retrieval scope agentName must be a string or null")
    return _scope_value(user_id), _scope_value(agent_name)


class FTS5RetrievalAdapter:
    """Scope-aware ``RetrievalPort`` adapter backed by one SQLite FTS5 DB.

    The index is derived data. Canonical facts remain in Markdown and storage
    notifications update only the addressed row. A deterministic composite
    document id prevents equal fact ids in two user/agent scopes from
    overwriting each other.
    """

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self._engine = FTS5Retrieval(db_path)

    @staticmethod
    def _document_id(fact_id: str, scope: dict[str, str | None]) -> str:
        scope_user, scope_agent = _scope_key(scope)
        return json.dumps([scope_user, scope_agent, fact_id], ensure_ascii=False, separators=(",", ":"))

    def _document(self, fact: dict[str, Any], scope: dict[str, str | None]) -> dict[str, Any]:
        fact_id = fact.get("id")
        content = fact.get("content")
        if not isinstance(fact_id, str) or not fact_id:
            raise ValueError("retrieval fact.id must be a non-empty string")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("retrieval fact.content must be a non-empty string")
        scope_user, scope_agent = _scope_key(scope)
        payload = dict(fact)
        payload["scope"] = {"userId": scope.get("userId"), "agentName": scope.get("agentName")}
        source = payload.get("source")
        return {
            "fact_id": self._document_id(fact_id, scope),
            "content": content,
            "category": str(payload.get("category") or "context"),
            "confidence": float(payload.get("confidence") or 0.5),
            "created_at": payload.get("createdAt") if isinstance(payload.get("createdAt"), str) else None,
            "scope_user": scope_user,
            "scope_agent": scope_agent,
            "source": source if isinstance(source, str) else json.dumps(source, ensure_ascii=False, default=str),
            "fact_data": payload,
        }

    def upsert(self, fact: dict[str, Any], *, scope: dict[str, str | None], path: str) -> None:
        del path  # Canonical location belongs to storage; the index is rebuildable.
        document = self._document(fact, scope)
        self._engine.index_fact(**document)

    def rebuild(self, records: list[tuple[dict[str, Any], dict[str, str | None], str]], *, scopes: list[dict[str, str | None]] | None) -> None:
        """Atomically replace the records selected by a storage rebuild."""
        documents = [self._document(fact, scope) for fact, scope, _path in records]
        encoded_scopes = None
        if scopes is not None:
            encoded_scopes = [_scope_key(scope) for scope in scopes]
        self._engine.replace_documents(documents, scopes=encoded_scopes)

    def remove(self, fact_id: str, *, scope: dict[str, str | None]) -> None:
        self._engine.remove_fact(self._document_id(fact_id, scope))

    def search(
        self,
        query: str,
        *,
        scopes: list[dict[str, str | None]],
        top_k: int,
        mode: str,
        filters: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        if not query.strip() or top_k <= 0:
            return []
        if mode not in {"hybrid", "fts5", "lexical"}:
            raise ValueError(f"unsupported FTS5 retrieval mode: {mode}")

        filters = filters or {}
        category = filters.get("category")
        if category is not None and not isinstance(category, str):
            raise ValueError("retrieval category filter must be a string")

        results: list[dict[str, Any]] = []
        per_scope_limit = top_k * 4
        for scope in scopes:
            scope_user, scope_agent = _scope_key(scope)
            for candidate in self._engine.search(
                query,
                scope_user=scope_user,
                scope_agent=scope_agent,
                category=category,
                top_k=per_scope_limit,
            ):
                fact = dict(candidate)
                score = float(fact.pop("score", 0.0))
                bm25_score = float(fact.pop("bm25_score", 0.0))
                if any(fact.get(key) != value for key, value in filters.items()):
                    continue
                results.append(
                    {
                        "fact": fact,
                        "score": score,
                        "matchType": "fts5",
                        "retrieval": {"bm25": bm25_score},
                    }
                )

        results.sort(key=lambda result: result["score"], reverse=True)
        return results[:top_k]

    def clear(self, *, scopes: list[dict[str, str | None]] | None = None) -> None:
        if scopes is None:
            self._engine.clear_index()
            return
        for scope in scopes:
            scope_user, scope_agent = _scope_key(scope)
            self._engine.clear_scope(scope_user=scope_user, scope_agent=scope_agent)

    def stats(self) -> dict[str, Any]:
        return self._engine.stats()

    def close(self) -> None:
        self._engine.close()


def create_fts5_retrieval(config: Any) -> FTS5RetrievalAdapter | None:
    """Build DeerMem's bundled adapter, using a persistent derived index.

    Standalone ``DeerMem`` instances with no configured storage root use an
    in-memory index. The host factory always injects an absolute storage root,
    so normal Gateway instances persist the rebuildable index below it.
    """
    storage_path = str(getattr(config, "storage_path", "") or "")
    if not storage_path:
        db_path: str | Path = ":memory:"
    else:
        index_dir = Path(storage_path) / ".retrieval"
        index_dir.mkdir(parents=True, exist_ok=True)
        db_path = index_dir / "memory-fts5.sqlite3"
    try:
        return FTS5RetrievalAdapter(db_path)
    except sqlite3.DatabaseError as exc:
        if db_path == ":memory:":
            logger.warning("SQLite FTS5 is unavailable; DeerMem will use substring retrieval: %s", exc)
            return None

        logger.warning("Derived memory retrieval index is invalid; recreating it: %s", exc)
        try:
            for path in (Path(db_path), Path(f"{db_path}-wal"), Path(f"{db_path}-shm")):
                path.unlink(missing_ok=True)
            return FTS5RetrievalAdapter(db_path)
        except (OSError, sqlite3.DatabaseError) as retry_exc:
            logger.warning(
                "SQLite FTS5 index recreation failed; DeerMem will use substring retrieval: %s",
                retry_exc,
            )
            return None
