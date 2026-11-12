"""
Multi-Signal Memory Retrieval — TF-IDF keyword-based semantic retrieval.

Implements a multi-signal scoring approach combining:
1. TF-IDF cosine similarity (semantic match)
2. Exact phrase match bonus
3. Recency boost
4. Importance scoring
5. Memory type classification (episodic, semantic, procedural)

No external APIs or vector databases required.
"""

import hashlib
import json
import math
import os
import re
from collections import Counter
from typing import Any


# ============================================================
# STOPWORDS
# ============================================================

STOPWORDS = set("""
a about after all also am an and any are as at be because been before being
between both but by came can come could did do does doing done due each few
for from further get got had has have having here how i if in into is it its
just like made make may me might more most much must my near need never no
nor not now of off old on once only or other our out over per pre put re said
same see she should show shown shows side since so some still such take tell
than that the their them then there these they thing things this those through
to too under up upon use used uses using very want was way we were what when
where which who why will with within without would yes yet you your
""".split())


# ============================================================
# TOKENIZATION & TF-IDF
# ============================================================

def tokenize(text: str) -> list[str]:
    """Tokenize and clean text into terms.

    Args:
        text: Raw text to tokenize.

    Returns:
        List of cleaned, lower-cased terms.
    """
    text = text.lower()
    terms = re.findall(r"[a-z0-9_\-]+", text)
    return [t for t in terms if t not in STOPWORDS and len(t) > 2]


def compute_tf(terms: list[str]) -> dict[str, float]:
    """Compute term frequency for a document.

    Args:
        terms: List of tokenized terms.

    Returns:
        Dict mapping term -> term frequency.
    """
    total = len(terms)
    if total == 0:
        return {}
    tf = Counter(terms)
    return {term: count / total for term, count in tf.items()}


def compute_idf(documents: list[list[str]]) -> dict[str, float]:
    """Compute inverse document frequency across all documents.

    Args:
        documents: List of tokenized documents.

    Returns:
        Dict mapping term -> IDF score.
    """
    n_docs = len(documents)
    doc_freq: Counter = Counter()
    for doc_terms in documents:
        unique_terms = set(doc_terms)
        for term in unique_terms:
            doc_freq[term] += 1

    idf: dict[str, float] = {}
    for term, freq in doc_freq.items():
        idf[term] = math.log((n_docs + 1) / (freq + 1)) + 1  # smoothed
    return idf


def tfidf_score(
    query_terms: list[str],
    doc_terms: list[str],
    idf: dict[str, float],
) -> float:
    """Compute TF-IDF cosine similarity between query and document.

    Args:
        query_terms: Tokenized query.
        doc_terms: Tokenized document.
        idf: Precomputed IDF mapping.

    Returns:
        Cosine similarity score (0.0 to 1.0).
    """
    if not query_terms or not doc_terms:
        return 0.0

    query_tf = compute_tf(query_terms)
    doc_tf = compute_tf(doc_terms)

    all_terms = set(query_tf.keys()) | set(doc_tf.keys())

    query_vec: list[float] = []
    doc_vec: list[float] = []
    for term in all_terms:
        q_tfidf = query_tf.get(term, 0) * idf.get(term, 1)
        d_tfidf = doc_tf.get(term, 0) * idf.get(term, 1)
        query_vec.append(q_tfidf)
        doc_vec.append(d_tfidf)

    dot = sum(a * b for a, b in zip(query_vec, doc_vec))
    norm_q = math.sqrt(sum(a * a for a in query_vec))
    norm_d = math.sqrt(sum(b * b for b in doc_vec))

    if norm_q == 0 or norm_d == 0:
        return 0.0

    return dot / (norm_q * norm_d)


# ============================================================
# MEMORY CLASSIFICATION
# ============================================================

PROCEDURAL_PATTERNS = [
    r"(I should|I must|I always|I never)",
    r"(Rule:|Pattern:|Strategy:)",
    r"(When .* happens?)",
    r"(Do not|Never|Always)",
    r"(If .* then)",
]

SEMANTIC_PATTERNS = [
    r"(is a|refers to|means)",
    r"(has |have |consists of)",
    r"(Credentials:|Infrastructure:|Key Systems)",
]


def classify_memory_type(content: str) -> str:
    """Classify a memory chunk as episodic, semantic, or procedural.

    Args:
        content: Memory text to classify.

    Returns:
        One of 'procedural', 'semantic', or 'episodic'.
    """
    for pat in PROCEDURAL_PATTERNS:
        if re.search(pat, content, re.IGNORECASE):
            return "procedural"
    for pat in SEMANTIC_PATTERNS:
        if re.search(pat, content, re.IGNORECASE):
            return "semantic"
    return "episodic"


# ============================================================
# CHUNKING
# ============================================================

def chunk_memory_text(text: str, max_chars: int = 800) -> list[str]:
    """Split memory text into semantic chunks at heading boundaries.

    Args:
        text: Full memory text (Markdown).
        max_chars: Maximum characters per chunk.

    Returns:
        List of chunk strings.
    """
    chunks: list[str] = []
    lines = text.split("\n")
    current_chunk = ""

    for line in lines:
        if line.startswith("## ") and current_chunk.strip():
            chunks.append(current_chunk.strip())
            current_chunk = line + "\n"
        elif line.startswith("### ") and current_chunk.strip():
            chunks.append(current_chunk.strip())
            current_chunk = line + "\n"
        elif len(current_chunk) + len(line) > max_chars and current_chunk.strip():
            chunks.append(current_chunk.strip())
            current_chunk = line + "\n"
        else:
            current_chunk += line + "\n"

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    return chunks


# ============================================================
# MEMORY RETRIEVAL CLASS
# ============================================================


class MemoryRetrieval:
    """Multi-signal memory retrieval using TF-IDF.

    Args:
        memory_file: Path to the primary memory file (e.g., MEMORY.md).
        memory_dir: Path to directory containing time-stamped memory files.
        index_file: Path where the serialized index is stored.
        agent_name: Name to use in scope metadata.
    """

    def __init__(
        self,
        memory_file: str | None = None,
        memory_dir: str | None = None,
        index_file: str = ".memory-index.json",
        agent_name: str = "default",
    ):
        self.memory_file = memory_file
        self.memory_dir = memory_dir
        self.index_file = index_file
        self.agent_name = agent_name

    # ----------------------------------------------------------
    # Index Building
    # ----------------------------------------------------------

    def build_index(self) -> list[dict[str, Any]]:
        """Build memory index from MEMORY.md and daily files.

        Returns:
            List of indexed memory entries.
        """
        memories: list[dict[str, Any]] = []

        # 1. Index primary memory file
        if self.memory_file and os.path.exists(self.memory_file):
            with open(self.memory_file, "r", encoding="utf-8") as f:
                content = f.read()
            chunks = chunk_memory_text(content)
            for chunk in chunks:
                if len(chunk) < 15:
                    continue
                mem_id = hashlib.sha256(chunk.encode()).hexdigest()[:16]
                memories.append({
                    "id": mem_id,
                    "type": classify_memory_type(chunk),
                    "scope": {"user": None, "agent": self.agent_name, "session": None},
                    "content": chunk,
                    "terms": tokenize(chunk),
                    "metadata": {
                        "source": os.path.basename(self.memory_file) if self.memory_file else "memory",
                        "importance": 0.8 if "## " in chunk[:80] else 0.4,
                        "access_count": 0,
                    },
                })

        # 2. Index daily memory files
        if self.memory_dir and os.path.exists(self.memory_dir):
            for fname in sorted(os.listdir(self.memory_dir)):
                if not fname.endswith(".md"):
                    continue
                fpath = os.path.join(self.memory_dir, fname)
                with open(fpath, "r", encoding="utf-8") as f:
                    content = f.read()
                chunks = chunk_memory_text(content)
                for chunk in chunks:
                    if len(chunk) < 20:
                        continue
                    mem_id = hashlib.sha256(chunk.encode()).hexdigest()[:16]
                    memories.append({
                        "id": mem_id,
                        "type": classify_memory_type(chunk),
                        "scope": {"user": None, "agent": self.agent_name, "session": None},
                        "content": chunk,
                        "terms": tokenize(chunk),
                        "metadata": {
                            "source": os.path.join(os.path.basename(self.memory_dir or ""), fname),
                            "importance": 0.4,
                            "access_count": 0,
                        },
                    })

        print(f"Indexing {len(memories)} memory chunks...")

        # Save index
        with open(self.index_file, "w") as f:
            json.dump(memories, f, indent=2)

        print(f"Index saved: {len(memories)} memories to {self.index_file}")
        return memories

    # ----------------------------------------------------------
    # Search
    # ----------------------------------------------------------

    def search(
        self,
        query: str,
        top_k: int = 5,
        mem_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search memory index by multi-signal scoring.

        Combines TF-IDF similarity + phrase match + recency + importance.

        Args:
            query: Search text.
            top_k: Maximum results to return.
            mem_type: Optional filter ('episodic', 'semantic', 'procedural').

        Returns:
            List of result dicts with score, type, source, content, id.
        """
        if not os.path.exists(self.index_file):
            print("No index found. Run build_index() first.")
            return []

        with open(self.index_file, "r") as f:
            memories = json.load(f)

        if not memories:
            return []

        query_terms = tokenize(query)
        if not query_terms:
            return []

        # Build global IDF
        all_terms = [m["terms"] for m in memories]
        idf = compute_idf(all_terms)

        scored: list[tuple[float, dict]] = []
        for mem in memories:
            if mem_type and mem["type"] != mem_type:
                continue

            # 1. TF-IDF cosine similarity
            sem_score = tfidf_score(query_terms, mem["terms"], idf)

            # 2. Exact phrase match bonus
            phrase_bonus = 0.1 if any(
                phrase.lower() in mem["content"].lower()
                for phrase in query.split("|")
            ) else 0.0

            # 3. Recency boost
            source = mem.get("metadata", {}).get("source", "")
            if source.startswith("memory/") and len(source) > 7:
                try:
                    day_part = source.split(".")[0].split("-")[-1]
                    day = int(day_part)
                    recency = min(day / 30.0, 1.0)
                except (ValueError, IndexError):
                    recency = 0.3
            elif source in ("MEMORY.md", "memory.md"):
                recency = 0.5
            else:
                recency = 0.2

            # 4. Importance boost
            importance = mem.get("metadata", {}).get("importance", 0.3)

            # Combined multi-signal score
            total_score = sem_score * 0.5 + phrase_bonus * 0.1 + recency * 0.2 + importance * 0.2
            scored.append((total_score, mem))

        # Sort by score descending
        scored.sort(key=lambda x: x[0], reverse=True)

        results = []
        for score, mem in scored[:top_k]:
            content_preview = mem["content"][:400]
            if len(mem["content"]) > 400:
                content_preview += "..."
            results.append({
                "score": round(score, 3),
                "type": mem["type"],
                "source": mem.get("metadata", {}).get("source", "unknown"),
                "content": content_preview,
                "id": mem["id"],
            })

        return results

    # ----------------------------------------------------------
    # Add Memory
    # ----------------------------------------------------------

    def add(
        self,
        content: str,
        mem_type: str | None = None,
        source: str = "conversation",
    ) -> str | None:
        """Add a new memory to the index.

        Args:
            content: Memory text to add.
            mem_type: Override memory type classification.
            source: Source label for the memory.

        Returns:
            Memory ID if added, None if duplicate or index missing.
        """
        if not os.path.exists(self.index_file):
            print("Index not found. Run build_index() first.")
            return None

        with open(self.index_file, "r") as f:
            memories = json.load(f)

        mem_id = hashlib.sha256(content.encode()).hexdigest()[:16]

        # Check for duplicates
        if any(m["id"] == mem_id for m in memories):
            print(f"Memory already exists: {mem_id}")
            return None

        if not mem_type:
            mem_type = classify_memory_type(content)

        mem = {
            "id": mem_id,
            "type": mem_type,
            "scope": {"user": None, "agent": self.agent_name, "session": None},
            "content": content,
            "terms": tokenize(content),
            "metadata": {
                "source": source,
                "importance": 0.5,
                "access_count": 0,
            },
        }

        memories.append(mem)

        with open(self.index_file, "w") as f:
            json.dump(memories, f, indent=2)

        print(f"Memory added: {mem_id} ({mem_type}): {content[:80]}...")
        return mem_id

    # ----------------------------------------------------------
    # Statistics
    # ----------------------------------------------------------

    def stats(self) -> dict[str, Any]:
        """Return index statistics.

        Returns:
            Dict with total memories, by type, by source, total terms.
        """
        if not os.path.exists(self.index_file):
            print("No index found.")
            return {}

        with open(self.index_file, "r") as f:
            memories = json.load(f)

        types: Counter = Counter(m["type"] for m in memories)
        sources: Counter = Counter(m["metadata"]["source"] for m in memories)
        total_terms = sum(len(m["terms"]) for m in memories)

        stats_data = {
            "total_memories": len(memories),
            "total_terms": total_terms,
            "by_type": dict(types.most_common()),
            "by_source": dict(sorted(sources.items())),
            "index_file": self.index_file,
            "index_bytes": os.path.getsize(self.index_file) if os.path.exists(self.index_file) else 0,
        }

        print(f"Total memories: {len(memories)}")
        print(f"Total terms: {total_terms}")
        print(f"By type:")
        for t, c in types.most_common():
            print(f"  {t}: {c}")
        print(f"By source:")
        for s, c in sorted(sources.items()):
            print(f"  {s}: {c}")

        return stats_data


# ============================================================
# COMMAND-LINE INTERFACE
# ============================================================

def main() -> None:
    """Command-line entry point for memory retrieval."""
    import sys

    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    # Default paths (adjust or pass as env vars)
    memory_file = os.environ.get("MEMORY_FILE", "MEMORY.md")
    memory_dir = os.environ.get("MEMORY_DIR", "memory")
    index_file = os.environ.get("MEMORY_INDEX", ".memory-index.json")

    retrieval = MemoryRetrieval(
        memory_file=memory_file if os.path.exists(memory_file) else None,
        memory_dir=memory_dir if os.path.exists(memory_dir) else None,
        index_file=index_file,
    )

    action = sys.argv[1]

    if action == "--index":
        retrieval.build_index()
    elif action == "--query":
        if len(sys.argv) < 3:
            print("Usage: --query <search text>")
            sys.exit(1)
        results = retrieval.search(" ".join(sys.argv[2:]))
        print(f"\n=== Top {len(results)} Results ===")
        for i, r in enumerate(results, 1):
            print(f"\n--- Result {i} [{r['type']}] (score: {r['score']}) ---")
            print(f"Source: {r['source']}")
            print(f"Content: {r['content'][:300]}")
    elif action == "--add":
        if len(sys.argv) < 3:
            print("Usage: --add <memory text>")
            sys.exit(1)
        retrieval.add(" ".join(sys.argv[2:]))
    elif action == "--stats":
        retrieval.stats()
    else:
        print(f"Unknown action: {action}")


if __name__ == "__main__":
    main()
