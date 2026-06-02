"""Transform functions: Sms responses → canonical models.

Pure functions that transform Sms-specific response shapes into
platform canonical models, populating source_metadata and provenance.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from deerflow.integrations.models.assessment import (
    AbnormalDetail,
    AbnormalEvent,
    AbnormalItem,
    AbnormalPoint,
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


def _safe_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def transform_abnormal_list(
    raw_data: dict[str, Any],
    system_key: str,
) -> tuple[AbnormalItem, ...]:
    """Transform SMS abnormal list response into AbnormalItem tuple.

    Args:
        raw_data: Response data from SMS /api/abnormal/list.
        system_key: The system key for provenance.

    Returns:
        Tuple of AbnormalItem instances.
    """
    rows = raw_data.get("rows") or []
    items: list[AbnormalItem] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        items.append(AbnormalItem(
            abnormal_id=str(row.get("id", "")),
            process_status=str(row.get("processStatus", "")),
            mac_path=str(row.get("macPath", "")),
            mac_name=str(row.get("macName", "")),
            component_name=str(row.get("componentName", "")),
            mac_id=str(row.get("macId", "")),
            component_id=str(row.get("componentId", "")),
            serious_health=_safe_float(row.get("seriousHealth")),
            latest_health=_safe_float(row.get("latestHealth")),
            first_event_time=_safe_int(row.get("firstEventTime")),
            lastest_event_time=_safe_int(row.get("lastestEventTime")),
            serious_level=_safe_int(row.get("seriousLevel")),
            latest_level=_safe_int(row.get("latestLevel")),
            event_count=_safe_int(row.get("eventCount")),
            recorder=str(row.get("recorder", "")),
            run_status=str(row.get("runStatus", "")),
            process_duration=_safe_int(row.get("processDuration")),
            mac_type=_safe_int(row.get("macType"), 1),
            defect_transfer_status=_safe_int(row.get("defectTransferStatus")),
            fault_transfer_status=_safe_int(row.get("faultTransferStatus")),
        ))
    return tuple(items)


def transform_abnormal_detail(
    raw_data: dict[str, Any],
    system_key: str,
    abnormal_id: str = "",
    mac_id: str = "",
    component_id: str = "",
) -> AbnormalDetail:
    """Transform SMS abnormal detail response into AbnormalDetail.

    Args:
        raw_data: Response data from SMS /api/abnormal/detail.
        system_key: The system key for provenance.
        abnormal_id: The abnormal ID (from the request).
        mac_id: Equipment ID supplemented from list data.
        component_id: Sub-device ID supplemented from list data.

    Returns:
        AbnormalDetail instance.
    """
    data = raw_data.get("data", raw_data) if isinstance(raw_data, dict) else {}

    events: list[AbnormalEvent] = []
    for evt in data.get("events") or []:
        if not isinstance(evt, dict):
            continue
        jp = evt.get("jumpParams") or {}
        points: list[AbnormalPoint] = []
        for pt in jp.get("points") or []:
            if not isinstance(pt, dict):
                continue
            points.append(AbnormalPoint(
                point_id=str(pt.get("pointId", "")),
                point_name=str(pt.get("pointName", "")),
                value_type=str(pt.get("valueType", "")),
                point_type=_safe_int(pt.get("pointType")),
            ))
        events.append(AbnormalEvent(
            time=_safe_int(evt.get("time")),
            health=_safe_float(evt.get("health")) if evt.get("health") is not None else None,
            type=str(evt.get("type", "")),
            run_status=str(evt.get("runStatus", "")),
            event_level=_safe_int(evt.get("eventLevel")),
            desc=str(evt.get("desc", "")),
            points=tuple(points),
            time_range_start=_safe_int(jp.get("startTime")),
            time_range_end=_safe_int(jp.get("endTime")),
            factory_id=str(jp.get("factoryId", "")),
        ))

    return AbnormalDetail(
        abnormal_id=abnormal_id,
        process_status=str(data.get("processStatus", "")),
        mac_path=str(data.get("macPath", "")),
        mac_name=str(data.get("macName", "")),
        component_name=str(data.get("componentName", "")),
        events=tuple(events),
        logs=tuple(data.get("logs") or []),
        ai_analyse=data.get("aiAnalyse"),
        risk_assessment=data.get("riskAssessment"),
        mac_id=mac_id,
        component_id=component_id,
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
