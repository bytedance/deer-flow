"""Weekly leaderboard utilities for academic accept/reject benchmarks."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from .schemas import AcademicEvalCase, AcademicEvalSummary

LEADERBOARD_SCHEMA_VERSION = "deerflow.academic_leaderboard.v1"


class LeaderboardEntry(BaseModel):
    """One leaderboard row for a discipline/venue/week bucket."""

    week: str
    discipline: str
    venue: str
    model_label: str
    run_name: str
    dataset_name: str | None = None
    benchmark_split: str = "unspecified"
    source_name: str | None = None
    updated_at: str
    case_count: int = 0
    average_overall_score: float = 0.0
    auc_accept_reject: float = 0.0
    accept_reject_score_gap: float = 0.0
    artifact_path: str | None = None


class LeaderboardBucket(BaseModel):
    """Leaderboard rows for one discipline+venue key."""

    discipline: str
    venue: str
    entries: list[LeaderboardEntry] = Field(default_factory=list)


class WeeklyLeaderboard(BaseModel):
    """Top-level leaderboard payload."""

    schema_version: str = LEADERBOARD_SCHEMA_VERSION
    cadence: str = "weekly"
    updated_at: str
    buckets: list[LeaderboardBucket] = Field(default_factory=list)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _iso_week_key(now: datetime | None = None) -> str:
    current = now or datetime.now(UTC)
    iso = current.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _roc_auc_pairwise(probs: list[float], labels: list[int]) -> float:
    pos = [p for p, y in zip(probs, labels, strict=False) if y == 1]
    neg = [p for p, y in zip(probs, labels, strict=False) if y == 0]
    if not pos or not neg:
        return 0.0
    wins: list[float] = []
    for p_pos in pos:
        for p_neg in neg:
            if p_pos > p_neg:
                wins.append(1.0)
            elif p_pos == p_neg:
                wins.append(0.5)
            else:
                wins.append(0.0)
    return _mean(wins)


def build_weekly_entries(
    *,
    cases: list[AcademicEvalCase],
    summary: AcademicEvalSummary,
    model_label: str,
    run_name: str,
    artifact_path: str | None = None,
    dataset_name: str | None = None,
    now: datetime | None = None,
) -> list[LeaderboardEntry]:
    """Build leaderboard rows grouped by discipline/venue."""
    if not cases:
        return []
    week_key = _iso_week_key(now)
    now_iso = _now_iso()
    result_lookup = {row.case_id: row for row in summary.results}
    buckets: dict[tuple[str, str], list[AcademicEvalCase]] = defaultdict(list)
    for case in cases:
        discipline = (case.domain or "unknown").strip() or "unknown"
        venue = (case.venue or "unknown").strip() or "unknown"
        buckets[(discipline, venue)].append(case)

    rows: list[LeaderboardEntry] = []
    for (discipline, venue), scoped_cases in buckets.items():
        overall_scores: list[float] = []
        accepted_scores: list[float] = []
        rejected_scores: list[float] = []
        probs: list[float] = []
        labels: list[int] = []
        for case in scoped_cases:
            row = result_lookup.get(case.case_id)
            if row is None:
                continue
            overall_scores.append(float(row.overall_score))
            if case.decision == "accepted":
                accepted_scores.append(float(row.overall_score))
                probs.append(float(row.predicted_accept_prob))
                labels.append(1)
            elif case.decision == "rejected":
                rejected_scores.append(float(row.overall_score))
                probs.append(float(row.predicted_accept_prob))
                labels.append(0)
        avg_overall = _mean(overall_scores)
        score_gap = (_mean(accepted_scores) - _mean(rejected_scores)) if accepted_scores and rejected_scores else 0.0
        rows.append(
            LeaderboardEntry(
                week=week_key,
                discipline=discipline,
                venue=venue,
                model_label=model_label,
                run_name=run_name,
                dataset_name=dataset_name,
                benchmark_split=scoped_cases[0].benchmark_split if scoped_cases else "unspecified",
                source_name=scoped_cases[0].source_name if scoped_cases else None,
                updated_at=now_iso,
                case_count=len(overall_scores),
                average_overall_score=round(avg_overall, 4),
                auc_accept_reject=round(_roc_auc_pairwise(probs, labels), 4),
                accept_reject_score_gap=round(score_gap, 4),
                artifact_path=artifact_path,
            )
        )
    rows.sort(key=lambda row: (row.discipline.lower(), row.venue.lower(), -row.average_overall_score))
    return rows


def merge_weekly_leaderboard(
    *,
    existing: WeeklyLeaderboard | None,
    new_entries: list[LeaderboardEntry],
    top_k: int = 12,
) -> WeeklyLeaderboard:
    """Merge new rows into existing leaderboard and keep ranked history."""
    merged_rows: list[LeaderboardEntry] = []
    if existing is not None:
        for bucket in existing.buckets:
            merged_rows.extend(bucket.entries)

    index: dict[tuple[str, str, str, str, str], LeaderboardEntry] = {}
    for row in merged_rows + new_entries:
        key = (
            row.week,
            row.discipline.lower(),
            row.venue.lower(),
            row.model_label.lower(),
            row.run_name.lower(),
        )
        current = index.get(key)
        if current is None or row.updated_at >= current.updated_at:
            index[key] = row

    bucket_rows: dict[tuple[str, str], list[LeaderboardEntry]] = defaultdict(list)
    for row in index.values():
        bucket_rows[(row.discipline, row.venue)].append(row)

    buckets: list[LeaderboardBucket] = []
    for (discipline, venue), rows in bucket_rows.items():
        ranked = sorted(
            rows,
            key=lambda item: (
                -item.average_overall_score,
                -item.auc_accept_reject,
                -item.case_count,
                item.updated_at,
            ),
        )[: max(1, top_k)]
        buckets.append(LeaderboardBucket(discipline=discipline, venue=venue, entries=ranked))
    buckets.sort(key=lambda row: (row.discipline.lower(), row.venue.lower()))
    return WeeklyLeaderboard(updated_at=_now_iso(), buckets=buckets)

