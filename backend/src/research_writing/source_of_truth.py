"""Single source of truth for manuscript numbers and semantic fact checks."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

_NUMERIC_MENTION_RE = re.compile(
    r"(?P<value>[-+]?\d+(?:\.\d+)?)\s*(?P<unit>%|percent|percentage|pct|ratio|fraction|ms|s|sec|seconds|min|minutes|h|hr|hours|kg|g|mg|ug|l|ml|m|cm|mm)?",
    flags=re.IGNORECASE,
)
_P_VALUE_RE = re.compile(r"\bp\s*[<=>]\s*(?P<value>\d+(?:\.\d+)?)", flags=re.IGNORECASE)
_CI_RE = re.compile(r"\b(?:ci|confidence interval)\b", flags=re.IGNORECASE)
_RATIO_UNITS = {"", "ratio", "fraction"}
_PERCENT_UNITS = {"%", "percent", "percentage", "pct"}
_UNIT_TO_BASE: dict[str, tuple[str, float]] = {
    "ms": ("s", 0.001),
    "s": ("s", 1.0),
    "sec": ("s", 1.0),
    "seconds": ("s", 1.0),
    "min": ("s", 60.0),
    "minutes": ("s", 60.0),
    "h": ("s", 3600.0),
    "hr": ("s", 3600.0),
    "hours": ("s", 3600.0),
    "kg": ("g", 1000.0),
    "g": ("g", 1.0),
    "mg": ("g", 0.001),
    "ug": ("g", 0.000001),
    "l": ("l", 1.0),
    "ml": ("l", 0.001),
    "m": ("m", 1.0),
    "cm": ("m", 0.01),
    "mm": ("m", 0.001),
}


class NumericFact(BaseModel):
    """Canonical numeric fact used across abstract/body/figures/rebuttal."""

    fact_id: str
    metric: str
    value: float
    unit: str | None = None
    context: str = ""
    source_artifact: str
    evidence_ids: list[str] = Field(default_factory=list)
    citation_ids: list[str] = Field(default_factory=list)
    population: str | None = None
    condition: str | None = None
    timepoint: str | None = None
    ci: str | None = None
    p_value: float | None = None
    derived_from: list[str] = Field(default_factory=list)


class FigureArtifact(BaseModel):
    figure_id: str
    caption: str
    artifact_path: str
    linked_fact_ids: list[str] = Field(default_factory=list)


class TableArtifact(BaseModel):
    table_id: str
    title: str
    artifact_path: str
    linked_fact_ids: list[str] = Field(default_factory=list)


class SemanticFactCheckItem(BaseModel):
    """Structured semantic fact-check result for one registered fact."""

    fact_id: str
    status: Literal["matched", "mismatch"] = "matched"
    matched_text: str | None = None
    normalized_fact_value: float | None = None
    normalized_text_value: float | None = None
    normalized_unit: str | None = None
    population_matched: bool | None = None
    condition_matched: bool | None = None
    timepoint_matched: bool | None = None
    ci_matched: bool | None = None
    p_value_matched: bool | None = None
    derived_from_matched: bool | None = None
    reason: str = ""


class SourceOfTruthSnapshot(BaseModel):
    """Persisted single-source-of-truth state."""

    numeric_facts: dict[str, NumericFact] = Field(default_factory=dict)
    figures: dict[str, FigureArtifact] = Field(default_factory=dict)
    tables: dict[str, TableArtifact] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


def _norm_unit(unit: str | None) -> str:
    raw = (unit or "").strip().lower()
    if raw in _PERCENT_UNITS:
        return "%"
    return raw


def _normalize_value_and_unit(value: float, unit: str | None) -> tuple[float, str]:
    normalized_unit = _norm_unit(unit)
    if normalized_unit in _PERCENT_UNITS:
        return float(value) / 100.0, "ratio"
    if normalized_unit in _RATIO_UNITS:
        return float(value), "ratio"
    if normalized_unit in _UNIT_TO_BASE:
        base_unit, multiplier = _UNIT_TO_BASE[normalized_unit]
        return float(value) * float(multiplier), base_unit
    return float(value), normalized_unit


def _units_compatible(left: str, right: str) -> bool:
    if left == right:
        return True
    if not left or not right:
        return True
    return False


def _value_close(left: float, right: float, *, tolerance_ratio: float = 0.05, tolerance_abs: float = 1e-4) -> bool:
    tolerance = max(tolerance_abs, abs(left) * tolerance_ratio)
    return abs(left - right) <= tolerance


def _extract_numeric_mentions(text: str) -> list[dict[str, Any]]:
    mentions: list[dict[str, Any]] = []
    if not isinstance(text, str) or not text.strip():
        return mentions
    for match in _NUMERIC_MENTION_RE.finditer(text):
        raw = match.group(0).strip()
        if not raw:
            continue
        try:
            value = float(match.group("value"))
        except Exception:
            continue
        unit = (match.group("unit") or "").strip()
        start = max(0, match.start() - 70)
        end = min(len(text), match.end() + 70)
        context = text[start:end]
        mentions.append(
            {
                "raw": raw,
                "value": value,
                "unit": unit,
                "context": context,
                "start": int(match.start()),
                "end": int(match.end()),
            }
        )
    return mentions


def _contains_token(text: str, token: str | None) -> bool | None:
    if token is None or not token.strip():
        return None
    return token.strip().lower() in text.lower()


def _p_value_matched(text: str, p_value: float | None, *, tolerance_ratio: float = 0.05) -> bool | None:
    if p_value is None:
        return None
    values = [float(match.group("value")) for match in _P_VALUE_RE.finditer(text)]
    if not values:
        return False
    return any(_value_close(float(v), float(p_value), tolerance_ratio=tolerance_ratio, tolerance_abs=1e-6) for v in values)


def _ci_matched(text: str, ci: str | None) -> bool | None:
    if ci is None or not ci.strip():
        return None
    lowered = text.lower()
    ci_norm = ci.strip().lower()
    if ci_norm in lowered:
        return True
    if _CI_RE.search(lowered):
        # Loose match: if CI phrase appears but exact value is paraphrased.
        return True
    return False


class SourceOfTruthStore:
    """File-backed source-of-truth registry."""

    def __init__(self, storage_path: Path):
        self.storage_path = storage_path
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> SourceOfTruthSnapshot:
        if not self.storage_path.exists():
            return SourceOfTruthSnapshot()
        data = json.loads(self.storage_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return SourceOfTruthSnapshot()
        return SourceOfTruthSnapshot.model_validate(data)

    def _save(self, snapshot: SourceOfTruthSnapshot) -> None:
        self.storage_path.write_text(snapshot.model_dump_json(indent=2), encoding="utf-8")

    def upsert_fact(self, fact: NumericFact) -> NumericFact:
        snapshot = self._load()
        snapshot.numeric_facts[fact.fact_id] = fact
        self._save(snapshot)
        return fact

    def upsert_figure(self, figure: FigureArtifact) -> FigureArtifact:
        snapshot = self._load()
        snapshot.figures[figure.figure_id] = figure
        self._save(snapshot)
        return figure

    def upsert_table(self, table: TableArtifact) -> TableArtifact:
        snapshot = self._load()
        snapshot.tables[table.table_id] = table
        self._save(snapshot)
        return table

    def get_fact(self, fact_id: str) -> NumericFact | None:
        return self._load().numeric_facts.get(fact_id)

    def list_facts(self) -> list[NumericFact]:
        return list(self._load().numeric_facts.values())

    def render_fact_sentence(self, fact_id: str) -> str:
        fact = self.get_fact(fact_id)
        if fact is None:
            raise ValueError(f"Fact '{fact_id}' not found")
        value_repr = f"{fact.value:g}"
        unit = (fact.unit or "").strip()
        if unit and unit != "%":
            value_part = f"{value_repr} {unit}"
        else:
            value_part = f"{value_repr}{unit}"
        context = f" in {fact.context}" if fact.context else ""
        return f"{fact.metric} is {value_part}{context}."

    def compile_results_paragraph(self, fact_ids: list[str]) -> str:
        lines = [self.render_fact_sentence(fid) for fid in fact_ids]
        return " ".join(lines).strip()

    def build_manifest(self) -> dict[str, Any]:
        snapshot = self._load()
        return {
            "numeric_facts": [fact.model_dump() for fact in snapshot.numeric_facts.values()],
            "figures": [figure.model_dump() for figure in snapshot.figures.values()],
            "tables": [table.model_dump() for table in snapshot.tables.values()],
            "metadata": snapshot.metadata,
        }

    def semantic_consistency_check(self, text: str, *, tolerance_ratio: float = 0.05, tolerance_abs: float = 1e-4) -> dict[str, Any]:
        """Run semantic fact checks with unit normalization and context validation."""
        facts = self.list_facts()
        mentions = _extract_numeric_mentions(text)
        if not facts:
            return {
                "matches": [],
                "mismatches": [],
                "unknown_mentions": [m["raw"] for m in mentions],
                "coverage": 0.0,
            }

        consumed_mentions: set[int] = set()
        match_items: list[SemanticFactCheckItem] = []
        mismatch_items: list[SemanticFactCheckItem] = []
        lowered = text.lower()

        for fact in facts:
            fact_value_norm, fact_unit_norm = _normalize_value_and_unit(fact.value, fact.unit)
            best_idx: int | None = None
            best_mention: dict[str, Any] | None = None
            best_delta: float | None = None
            for idx, mention in enumerate(mentions):
                mention_value_norm, mention_unit_norm = _normalize_value_and_unit(float(mention["value"]), str(mention.get("unit") or ""))
                if not _units_compatible(fact_unit_norm, mention_unit_norm):
                    continue
                if not _value_close(fact_value_norm, mention_value_norm, tolerance_ratio=tolerance_ratio, tolerance_abs=tolerance_abs):
                    continue
                delta = abs(fact_value_norm - mention_value_norm)
                if best_delta is None or delta < best_delta:
                    best_idx = idx
                    best_mention = mention
                    best_delta = delta

            population_matched = _contains_token(lowered, fact.population)
            condition_matched = _contains_token(lowered, fact.condition)
            timepoint_matched = _contains_token(lowered, fact.timepoint)
            ci_matched = _ci_matched(text, fact.ci)
            p_matched = _p_value_matched(text, fact.p_value, tolerance_ratio=tolerance_ratio)
            derived_from_ok = all(self.get_fact(fid) is not None for fid in fact.derived_from) if fact.derived_from else None

            if best_mention is not None and best_idx is not None:
                consumed_mentions.add(best_idx)
                row = SemanticFactCheckItem(
                    fact_id=fact.fact_id,
                    status="matched",
                    matched_text=str(best_mention["raw"]),
                    normalized_fact_value=round(fact_value_norm, 8),
                    normalized_text_value=round(float(_normalize_value_and_unit(float(best_mention["value"]), str(best_mention.get("unit") or ""))[0]), 8),
                    normalized_unit=fact_unit_norm or _norm_unit(str(best_mention.get("unit") or "")) or None,
                    population_matched=population_matched,
                    condition_matched=condition_matched,
                    timepoint_matched=timepoint_matched,
                    ci_matched=ci_matched,
                    p_value_matched=p_matched,
                    derived_from_matched=derived_from_ok,
                )
                # Context constraints are soft checks: numeric match is primary.
                soft_fail = any(v is False for v in (population_matched, condition_matched, timepoint_matched, ci_matched, p_matched, derived_from_ok))
                if soft_fail:
                    row.status = "mismatch"
                    row.reason = "Numeric value matched, but one or more semantic qualifiers were not satisfied."
                    mismatch_items.append(row)
                else:
                    row.reason = "Numeric and semantic qualifiers are consistent with source-of-truth."
                    match_items.append(row)
                continue

            mismatch_items.append(
                SemanticFactCheckItem(
                    fact_id=fact.fact_id,
                    status="mismatch",
                    matched_text=None,
                    normalized_fact_value=round(fact_value_norm, 8),
                    normalized_text_value=None,
                    normalized_unit=fact_unit_norm or None,
                    population_matched=population_matched,
                    condition_matched=condition_matched,
                    timepoint_matched=timepoint_matched,
                    ci_matched=ci_matched,
                    p_value_matched=p_matched,
                    derived_from_matched=derived_from_ok,
                    reason="No semantically compatible numeric mention found in text.",
                )
            )

        unknown_mentions = [mention["raw"] for idx, mention in enumerate(mentions) if idx not in consumed_mentions]
        coverage = float(len(match_items)) / float(len(facts)) if facts else 0.0
        return {
            "matches": [item.model_dump() for item in match_items],
            "mismatches": [item.model_dump() for item in mismatch_items],
            "unknown_mentions": unknown_mentions,
            "coverage": round(coverage, 4),
        }

    def consistency_check(self, text: str) -> list[str]:
        """Find numeric mentions in text that are not semantically grounded by fact store."""
        report = self.semantic_consistency_check(text)
        unknown = report.get("unknown_mentions")
        if isinstance(unknown, list):
            return [str(item) for item in unknown]
        return []
