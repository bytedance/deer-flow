"""Deterministic, offline QA grader for the pr4789 reproduction protocol.

The grader is blind by construction: it receives only a prediction string and a
reference string, never a policy identity. Its behavior is versioned as
``GRADER_VERSION`` and pinned by ``qa.grader_version`` in the evaluation config;
any behavioral change requires a new version string.

Rule order, following the protocol disclosed in pr4789:

1. reject an empty prediction or the literal ``INSUFFICIENT`` sentinel;
2. accept exact equality of the normalized token sequences;
3. accept containment of one normalized token sequence in the other as a
   contiguous subsequence (token-level, so ``5`` never matches inside ``25``);
4. accept a numeric prediction whose integer tokens all fall inside an explicit
   ``ranging from X ... to Y`` reference range;
5. reject conflicting integer tokens when both sides contain integers;
6. otherwise require at least ``OVERLAP_THRESHOLD`` unique non-stopword token
   overlap in both directions.

Normalization lowercases, replaces every non-alphanumeric character with a
space, and maps the English number words one through ten and fifteen to digits.
The stopword list is a fixed part of this grader version; ``yes``, ``no``, and
``not`` are deliberately excluded from it because negation can be the entire
answer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

GRADER_VERSION = "deterministic-overlap-v1"
OVERLAP_THRESHOLD = 0.6

_INSUFFICIENT_SENTINEL = "insufficient"
_NON_ALPHANUMERIC = re.compile(r"[^0-9a-z]+")
_REFERENCE_RANGE = re.compile(r"\branging from (\d+)(?:\s\S+)*?\sto (\d+)\b")

_NUMBER_WORDS = {
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "ten": "10",
    "fifteen": "15",
}

_STOPWORDS = frozenset(
    (
        "a an the this that these those all any both each few more most other some such same own "
        "i you he she it we they me him her us them my your his its our their mine yours hers ours theirs whose "
        "am is are was were be been being do does did doing have has had having will would shall should can could may might must "
        "and or but nor so yet if then than because while until once although though whether "
        "of in on at by for with about against between into through during before after above below to from up down out off over under again further "
        "what which who whom when where why how there here only too very just also"
    ).split()
)


@dataclass(frozen=True)
class GradeResult:
    correct: bool
    rule: str


def normalize_answer(text: str) -> list[str]:
    tokens = _NON_ALPHANUMERIC.split(text.lower())
    return [_NUMBER_WORDS.get(token, token) for token in tokens if token]


def _is_contiguous_subsequence(needle: list[str], haystack: list[str]) -> bool:
    if not needle or len(needle) > len(haystack):
        return False
    return any(haystack[start : start + len(needle)] == needle for start in range(len(haystack) - len(needle) + 1))


def _integer_tokens(tokens: list[str]) -> set[int]:
    return {int(token) for token in tokens if token.isdigit()}


def grade_answer(prediction: str, reference: str) -> GradeResult:
    prediction_tokens = normalize_answer(prediction)
    reference_tokens = normalize_answer(reference)
    if not reference_tokens:
        raise ValueError("The grading reference must contain at least one token")
    if not prediction_tokens:
        return GradeResult(correct=False, rule="empty-prediction")
    if prediction_tokens == [_INSUFFICIENT_SENTINEL]:
        return GradeResult(correct=False, rule="insufficient")
    if prediction_tokens == reference_tokens:
        return GradeResult(correct=True, rule="exact")
    if _is_contiguous_subsequence(reference_tokens, prediction_tokens) or _is_contiguous_subsequence(prediction_tokens, reference_tokens):
        return GradeResult(correct=True, rule="substring")

    prediction_integers = _integer_tokens(prediction_tokens)
    reference_integers = _integer_tokens(reference_tokens)
    range_match = _REFERENCE_RANGE.search(" ".join(reference_tokens))
    if range_match and prediction_integers:
        low, high = sorted((int(range_match.group(1)), int(range_match.group(2))))
        if all(low <= value <= high for value in prediction_integers):
            return GradeResult(correct=True, rule="numeric-range")
    if prediction_integers and reference_integers and prediction_integers != reference_integers:
        return GradeResult(correct=False, rule="numeric-conflict")

    prediction_content = {token for token in prediction_tokens if token not in _STOPWORDS}
    reference_content = {token for token in reference_tokens if token not in _STOPWORDS}
    if not prediction_content or not reference_content:
        return GradeResult(correct=False, rule="overlap-reject")
    shared = prediction_content & reference_content
    if len(shared) / len(prediction_content) >= OVERLAP_THRESHOLD and len(shared) / len(reference_content) >= OVERLAP_THRESHOLD:
        return GradeResult(correct=True, rule="overlap-accept")
    return GradeResult(correct=False, rule="overlap-reject")
