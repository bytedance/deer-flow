"""Jaccard similarity of unique, case-folded word tokens."""

import re


def words(query: str) -> list[str]:
    return re.findall(r"[^\W_]+", query.casefold())


def similarity(left: str, right: str) -> float:
    a, b = set(words(left)), set(words(right))
    union = a | b
    return len(a & b) / len(union) if union else 1.0
