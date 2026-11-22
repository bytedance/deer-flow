"""Cosine similarity of normalized sentence embeddings."""

import math

MODEL = "sentence-transformers/all-MiniLM-L6-v2"
REVISION = "c9745ed1d9f207416be6d2e6f8de32d1f16199bf"


def load_encoder():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(MODEL, revision=REVISION, device="cpu")


def similarities(query: str, references: list[str], encoder) -> list[float]:
    vectors = encoder.encode([query, *references], normalize_embeddings=True, show_progress_bar=False)
    scores = [float(dot) for dot in vectors[1:] @ vectors[0]]
    if len(scores) != len(references) or not all(math.isfinite(score) for score in scores):
        raise ValueError("Invalid sentence embedding output")
    return [max(-1.0, min(1.0, score)) for score in scores]
