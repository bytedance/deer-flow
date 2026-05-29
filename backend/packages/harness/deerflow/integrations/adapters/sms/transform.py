"""Transform functions: Sms responses → canonical models.

Pure functions that transform Sms-specific response shapes into
platform canonical models, populating source_metadata and provenance.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from deerflow.integrations.models.assessment import (
    AnomalyStats,
    EquipmentRisk,
    HealthAssessment,
    RiskItem,
    RiskRanking,
)
from deerflow.integrations.models.provenance import Provenance


def _build_provenance(
    system_key: str,
    capability_key: str,
    query_params: dict[str, Any] | None = None,
) -> Provenance:
    """Build a Provenance instance for Sms data."""
    return Provenance(
        source_system_key=system_key,
        source_system_type="sms",
        capability_key=capability_key,
        fetched_at=datetime.now(),
        query_params=query_params or {},
    )


def transform_health_assessment(
    raw_data: dict[str, Any],
    system_key: str,
) -> HealthAssessment:
    """Transform Sms health assessment response to HealthAssessment.

    Args:
        raw_data: Response from Sms health assessment API.
        system_key: The system key for provenance.

    Returns:
        HealthAssessment instance.
    """
    provenance = _build_provenance(system_key, "health.assessment")

    # Build risk items
    risk_items: list[RiskItem] = []
    for item in raw_data.get("riskItems") or raw_data.get("risk_items") or []:
        risk_item = RiskItem(
            risk_id=str(item.get("id") or item.get("riskId") or ""),
            asset_id=str(item.get("equipmentId") or item.get("asset_id") or ""),
            risk_type=str(item.get("riskType") or item.get("type") or "unknown"),
            severity=str(item.get("severity") or item.get("level") or "info"),
            description=str(item.get("description") or item.get("message") or ""),
            recommendation=str(item.get("recommendation") or item.get("suggestion") or ""),
            detected_at=_parse_timestamp(item.get("detectedAt") or item.get("createTime")),
            confidence=float(item.get("confidence") or 1.0),
            source_metadata={
                "raw_severity": item.get("severity"),
                "category": item.get("category"),
            },
        )
        risk_items.append(risk_item)

    # Build dimensions
    dimensions: dict[str, float] = {}
    for dim in raw_data.get("dimensions") or raw_data.get("scores") or []:
        if isinstance(dim, dict):
            name = dim.get("name") or dim.get("dimension")
            score = dim.get("score") or dim.get("value")
            if name and score is not None:
                dimensions[str(name)] = float(score)

    assessed_at = _parse_timestamp(
        raw_data.get("assessedAt") or raw_data.get("createTime") or raw_data.get("updateTime")
    )

    return HealthAssessment(
        assessment_id=str(raw_data.get("id") or raw_data.get("assessmentId") or ""),
        asset_id=str(raw_data.get("equipmentId") or raw_data.get("asset_id") or ""),
        overall_score=float(raw_data.get("overallScore") or raw_data.get("score") or 0),
        overall_status=str(raw_data.get("overallStatus") or raw_data.get("status") or "unknown"),
        summary=str(raw_data.get("summary") or raw_data.get("conclusion") or ""),
        dimensions=dimensions,
        risk_items=tuple(risk_items),
        assessed_at=assessed_at,
        assessor=str(raw_data.get("assessor") or raw_data.get("modelVersion") or ""),
        source_metadata={
            "raw_status": raw_data.get("overallStatus"),
            "data_quality": raw_data.get("dataQuality"),
        },
        provenance=provenance,
    )


def transform_anomaly_stats(
    raw_data: dict[str, Any],
    system_key: str,
) -> AnomalyStats:
    """Transform Sms anomaly statistics response to AnomalyStats.

    Args:
        raw_data: Response from Sms anomaly statistics API.
        system_key: The system key for provenance.

    Returns:
        AnomalyStats instance.
    """
    provenance = _build_provenance(system_key, "health.anomaly_statistics")

    # Build severity breakdown
    by_severity: dict[str, int] = {}
    for entry in raw_data.get("bySeverity") or raw_data.get("severityBreakdown") or []:
        if isinstance(entry, dict):
            key = str(entry.get("severity") or entry.get("level") or "unknown")
            count = int(entry.get("count") or entry.get("value") or 0)
            by_severity[key] = count

    # Build type breakdown
    by_type: dict[str, int] = {}
    for entry in raw_data.get("byType") or raw_data.get("typeBreakdown") or []:
        if isinstance(entry, dict):
            key = str(entry.get("type") or entry.get("name") or "unknown")
            count = int(entry.get("count") or entry.get("value") or 0)
            by_type[key] = count

    return AnomalyStats(
        stats_id=str(raw_data.get("id") or raw_data.get("statsId") or ""),
        asset_id=str(raw_data.get("equipmentId") or raw_data.get("asset_id") or ""),
        total_anomalies=int(raw_data.get("totalAnomalies") or raw_data.get("total") or 0),
        anomaly_rate=float(raw_data.get("anomalyRate") or raw_data.get("rate") or 0),
        by_severity=by_severity,
        by_type=by_type,
        time_range_start=_parse_timestamp(raw_data.get("startTime") or raw_data.get("timeRangeStart")),
        time_range_end=_parse_timestamp(raw_data.get("endTime") or raw_data.get("timeRangeEnd")),
        source_metadata={
            "sample_count": raw_data.get("sampleCount"),
            "window_size": raw_data.get("windowSize"),
        },
        provenance=provenance,
    )


def transform_risk_ranking(
    raw_data: dict[str, Any],
    system_key: str,
    tenant_id: str = "",
) -> RiskRanking:
    """Transform Sms risk ranking response to RiskRanking.

    Args:
        raw_data: Response from Sms risk ranking API.
        system_key: The system key for provenance.
        tenant_id: Tenant identifier.

    Returns:
        RiskRanking instance.
    """
    provenance = _build_provenance(system_key, "health.risk_ranking")

    # Build equipment risk entries
    rankings: list[EquipmentRisk] = []
    for entry in raw_data.get("rankings") or raw_data.get("list") or raw_data.get("items") or []:
        if not isinstance(entry, dict):
            continue

        top_risks_raw = entry.get("topRisks") or entry.get("risks") or []
        top_risks = tuple(str(r) for r in top_risks_raw) if top_risks_raw else ()

        risk = EquipmentRisk(
            asset_id=str(entry.get("equipmentId") or entry.get("asset_id") or ""),
            asset_name=str(entry.get("equipmentName") or entry.get("name") or ""),
            risk_level=str(entry.get("riskLevel") or entry.get("level") or "unknown"),
            risk_score=float(entry.get("riskScore") or entry.get("score") or 0),
            top_risks=top_risks,
            last_assessed_at=_parse_timestamp(entry.get("lastAssessedAt") or entry.get("updateTime")),
        )
        if risk.asset_id:
            rankings.append(risk)

    generated_at = _parse_timestamp(
        raw_data.get("generatedAt") or raw_data.get("createTime")
    )

    return RiskRanking(
        ranking_id=str(raw_data.get("id") or raw_data.get("rankingId") or ""),
        tenant_id=tenant_id or str(raw_data.get("tenantId") or ""),
        rankings=tuple(rankings),
        generated_at=generated_at,
        scope=str(raw_data.get("scope") or ""),
        source_metadata={
            "total_equipment": raw_data.get("totalEquipment"),
            "ranking_model": raw_data.get("model"),
        },
        provenance=provenance,
    )


def _parse_timestamp(raw: Any) -> datetime | None:
    """Parse various timestamp formats."""
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw
    if isinstance(raw, (int, float)):
        try:
            return datetime.fromtimestamp(raw / 1000 if raw > 1e12 else raw)
        except (OSError, OverflowError, ValueError):
            return None
    if isinstance(raw, str):
        if raw.isdigit():
            return _parse_timestamp(int(raw))
        for fmt in (
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%d",
        ):
            try:
                return datetime.strptime(raw, fmt)
            except ValueError:
                continue
    return None
