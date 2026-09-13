from __future__ import annotations

import asyncio
import re
import sqlite3
import time

import numpy as np

from common import PROTOCOL, ROOT, LiveClient, clip, tokens, write_json
from prepare import record_chunks

STOP = set("a an the is are was were be been being to of for in on at by with and or as from this that these those it its i me my you your we our they their he she his her do does did have has had what which who whom whose when where why how can could would should will shall about please tell give many much than then there here any some all also into after before during".split())


def lexical_terms(text: str, *, query: bool = False) -> list[str]:
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    latin = re.findall(r"[a-zA-Z0-9]+", text.lower())
    cjk = []
    for run in re.findall(r"[\u3400-\u9fff]+", text):
        cjk.extend(run[i:i + 2] for i in range(max(1, len(run) - 1)))
    terms = latin + cjk
    return list(dict.fromkeys(t for t in terms if t not in STOP)) if query else terms


class HistoryIndex:
    def __init__(self, records: list[dict], case_id: str):
        self.records = records
        self.by_id = {r["id"]: r for r in records}
        self.chunks = record_chunks(records, PROTOCOL["archive_chunk_tokens"], PROTOCOL["archive_chunk_overlap"])
        self.case_id = case_id
        self.db = sqlite3.connect(":memory:")
        self.db.execute("CREATE VIRTUAL TABLE history USING fts5(body, tokenize='porter unicode61')")
        self.db.executemany("INSERT INTO history(rowid, body) VALUES (?, ?)",
                            [(i + 1, " ".join(lexical_terms(c["text"]))) for i, c in enumerate(self.chunks)])
        self.vectors: np.ndarray | None = None
        self.embedding_seconds = 0.0

    def keyword_ranks(self, query: str, limit: int = 80) -> list[int]:
        terms = lexical_terms(query, query=True)[:60]
        if not terms:
            return []
        expression = " OR ".join('"' + t.replace('"', '""') + '"' for t in terms)
        rows = self.db.execute("SELECT rowid FROM history WHERE history MATCH ? ORDER BY bm25(history), rowid LIMIT ?", (expression, limit))
        return [row[0] - 1 for row in rows]

    async def build_vectors(self, client: LiveClient) -> None:
        if self.vectors is not None:
            return
        start = time.monotonic()
        # Bound each request by both item count and practical token volume.
        batches = [self.chunks[i:i + 32] for i in range(0, len(self.chunks), 32)]
        result = []
        for i, batch in enumerate(batches):
            result.append(await client.embed([c["rendered"] for c in batch], tag=f"{self.case_id}:index:{i}"))
        self.vectors = np.vstack(result) if result else np.empty((0, 1024), dtype=np.float32)
        self.embedding_seconds = time.monotonic() - start

    def pack(self, ranking: list[int], budget: int) -> list[dict]:
        selected, used, per_record = [], 0, {}
        for index in ranking:
            chunk = self.chunks[index]
            rid = chunk["record_id"]
            if per_record.get(rid, 0) >= 2:
                continue
            n = tokens(chunk["rendered"]) + 2
            if used + n > budget:
                continue
            selected.append(chunk)
            per_record[rid] = per_record.get(rid, 0) + 1
            used += n
        return selected

    async def search(self, query: str, mode: str, client: LiveClient, budget: int | None = None) -> dict:
        budget = budget or PROTOCOL["retrieval_context_tokens"]
        start = time.monotonic()
        lexical = self.keyword_ranks(query)
        dense = []
        if mode in {"hybrid", "dense"}:
            await self.build_vectors(client)
            query_vector = (await client.embed([query], query=True, tag=f"{self.case_id}:query"))[0]
            scores = self.vectors @ query_vector
            dense = sorted(range(len(scores)), key=lambda i: (-float(scores[i]), i))[:80]
        if mode == "keyword":
            ranking = lexical
        elif mode == "dense":
            ranking = dense
        elif mode == "hybrid":
            scores = {}
            for ranks in (lexical, dense):
                for rank, index in enumerate(ranks, 1):
                    scores[index] = scores.get(index, 0) + 1 / (60 + rank)
            ranking = sorted(scores, key=lambda i: (-scores[i], i))
        else:
            raise ValueError(mode)
        hits = self.pack(ranking, budget)
        return {"mode": mode, "query": query, "hits": hits,
                "tokens": sum(tokens(c["rendered"]) + 2 for c in hits),
                "seconds": time.monotonic() - start,
                "ranking_ids": [self.chunks[i]["id"] for i in ranking]}

    def read(self, record_id: str, radius: int = 1, budget: int = 1500) -> dict:
        rid = record_id.split("-c")[0]
        if rid not in self.by_id:
            return {"error": "unknown_record_id"}
        position = next(i for i, r in enumerate(self.records) if r["id"] == rid)
        radius = max(0, min(radius, 2))
        selected = self.records[max(0, position - radius):position + radius + 1]
        text = "\n\n".join(f"[{r['id']}] {r['date']} {r['role']}\n{r['content']}" for r in selected)
        return {"record_id": rid, "text": clip(text, budget), "truncated": tokens(text) > budget}

    def close(self) -> None:
        self.db.close()
