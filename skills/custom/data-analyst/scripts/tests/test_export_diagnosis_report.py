"""Unit tests for export_diagnosis_report.py render functions.

Run: python -m pytest tests/test_export_diagnosis_report.py -v
"""

from export_diagnosis_report import (
    render_diagnosis_markdown,
    _section_report_meta,
    _section_cross_device_correlation,
    _section_impact_assessment,
    _section_root_cause_ranking,
    _section_aggregated_recommendations,
    _section_data_quality,
)


def test_single_device_basic_format():
    """Test single-device (non-aggregated) markdown rendering."""
    payload = {
        "report_meta": {
            "kind": "centrifugal_compressor",
            "rules_skill": "vibration-fault-diagnosis",
            "data_source": "InS",
            "generated_at": "2026-05-25T10:00:00",
        },
        "equipment_summary": [
            {
                "equipment_name": "压缩机A",
                "operation_phase": "满负荷",
                "alarm_status": "告警",
                "max_value": {
                    "point": "bearing_temp",
                    "feature": "max_value",
                    "value": 85.2,
                    "unit": "°C",
                },
            }
        ],
        "evidence_chain": [
            {
                "category": "温度",
                "equipment_name": "压缩机A",
                "point": "bearing_temp",
                "feature": "max_value",
                "value": 85.2,
                "threshold": 80.0,
                "verdict": "exceed",
            }
        ],
        "rule_matches": [
            {
                "fault_family": "轴承磨损",
                "fault_subtype": "热损伤",
                "equipment_name": "压缩机A",
                "confidence": "high",
                "score": 0.85,
                "rule_section": "R001",
                "supporting_evidence_indices": [0],
                "marginal_evidence_indices": [],
                "missing_evidence": [],
            }
        ],
        "result_summary": {"overall_verdict": "fault"},
        "recommendations": ["更换轴承", "降低负荷运行"],
        "warnings": [],
    }

    md = render_diagnosis_markdown(payload)

    assert "# 故障诊断报告" in md
    assert "## 1. 设备与任务" in md
    assert "centrifugal_compressor" in md
    assert "压缩机A" in md
    assert "## 2. 异常发现" in md
    assert "85.2" in md
    assert "## 3. 证据链" in md
    assert "超阈值" in md
    assert "## 4. 诊断结论" in md
    assert "轴承磨损" in md
    assert "## 5. 差异诊断" in md
    assert "## 6. 处置建议" in md
    assert "更换轴承" in md


def test_single_device_normal_verdict():
    """Test rendering when overall verdict is normal."""
    payload = {
        "report_meta": {"kind": "pump", "generated_at": "2026-05-25"},
        "equipment_summary": [],
        "evidence_chain": [],
        "rule_matches": [],
        "result_summary": {"overall_verdict": "normal"},
        "recommendations": [],
        "warnings": [],
    }

    md = render_diagnosis_markdown(payload)

    assert "机组正常" in md
    assert "无需要展示的故障" in md


def test_single_device_with_warnings():
    """Test rendering with execution warnings."""
    payload = {
        "report_meta": {"kind": "pump"},
        "equipment_summary": [],
        "evidence_chain": [],
        "rule_matches": [],
        "result_summary": {},
        "recommendations": [],
        "warnings": ["数据完整率低: 75%", "部分传感器离线"],
    }

    md = render_diagnosis_markdown(payload)

    assert "执行告警" in md
    assert "数据完整率低" in md
    assert "传感器离线" in md


def test_aggregated_format_detected():
    """Test that per_device key triggers aggregated rendering."""
    payload = {
        "analysis_type": "diagnosis",
        "report_meta": {"total_devices": 1, "capability_tier": "basic"},
        "per_device": [
            {
                "equipment_id": "EQ001",
                "equipment_name": "设备1",
                "key_findings": [],
                "root_causes": [],
                "recommendations": [],
            }
        ],
        "cross_device_correlation": {"correlated_root_causes": []},
        "impact_assessment": {
            "affected_equipment_count": 1,
            "severity_distribution": {"low": 0, "medium": 0, "high": 0, "critical": 0},
            "estimated_downtime_hours": 0,
            "business_impact": "影响较小",
        },
        "root_cause_ranking": [],
        "recommendations": [],
    }

    md = render_diagnosis_markdown(payload)

    assert "# 多设备故障诊断报告" in md
    assert "## 报告信息" in md
    assert "## 设备诊断摘要" in md
    assert "设备1" in md


def test_aggregated_capability_tier_display():
    """Test capability tier is displayed in report meta."""
    payload = {
        "report_meta": {"total_devices": 2},
        "capability_tier": "pro",
        "per_device": [],
        "cross_device_correlation": {"correlated_root_causes": []},
        "impact_assessment": {},
        "root_cause_ranking": [],
        "recommendations": [],
    }

    md = _section_report_meta(payload)
    assert "**能力等级**：PRO" in md


def test_aggregated_model_fallback():
    """Test model fallback warning is rendered."""
    payload = {
        "report_meta": {"total_devices": 1},
        "capability_tier": "ultra",
        "model_fallback": True,
        "per_device": [],
    }

    md = _section_report_meta(payload)
    assert "模型回退" in md
    assert "Ultra 模型不可用" in md


def test_aggregated_schedule_label():
    """Test schedule label is rendered when present."""
    payload = {
        "report_meta": {"total_devices": 1},
        "capability_tier": "pro",
        "schedule_label": "定时巡检 · 日报嵌入",
        "per_device": [],
    }

    md = _section_report_meta(payload)
    assert "调度标签" in md
    assert "定时巡检" in md


def test_cross_device_correlation_section():
    """Test cross-device correlation rendering with correlated root causes."""
    payload = {
        "cross_device_correlation": {
            "correlated_root_causes": [
                {
                    "root_cause_id": "bearing_wear",
                    "root_cause_label": "轴承磨损",
                    "correlation_strength": "high",
                    "affected_devices": [
                        {"equipment_id": "EQ001", "equipment_name": "设备1"},
                        {"equipment_id": "EQ002", "equipment_name": "设备2"},
                        {"equipment_id": "EQ003", "equipment_name": "设备3"},
                    ],
                    "max_severity": "high",
                    "max_likelihood": "high",
                },
                {
                    "root_cause_id": "unbalance",
                    "root_cause_label": "不平衡",
                    "correlation_strength": "low",
                    "affected_devices": [
                        {"equipment_id": "EQ001", "equipment_name": "设备1"},
                    ],
                    "max_severity": "medium",
                    "max_likelihood": "low",
                },
            ]
        }
    }

    md = _section_cross_device_correlation(payload)

    assert "跨设备根因关联" in md
    assert "轴承磨损" in md
    assert "强关联" in md
    assert "设备1" in md
    assert "设备2" in md
    assert "设备3" in md
    assert "不平衡" in md
    assert "弱关联" in md


def test_cross_device_correlation_empty():
    """Test cross-device correlation returns empty when no correlations."""
    payload = {"cross_device_correlation": {"correlated_root_causes": []}}
    md = _section_cross_device_correlation(payload)
    assert md == ""


def test_impact_assessment_section():
    """Test impact assessment rendering."""
    payload = {
        "impact_assessment": {
            "affected_equipment_count": 3,
            "severity_distribution": {
                "critical": 1,
                "high": 1,
                "medium": 0,
                "low": 1,
            },
            "estimated_downtime_hours": 24,
            "business_impact": "严重影响生产，建议立即停机检修",
        }
    }

    md = _section_impact_assessment(payload)

    assert "影响评估" in md
    assert "受影响设备数**：3" in md
    assert "严重：1" in md
    assert "高：1" in md
    assert "24 小时" in md
    assert "严重影响生产" in md


def test_impact_assessment_empty():
    """Test impact assessment returns empty when no data."""
    payload = {"impact_assessment": {}}
    md = _section_impact_assessment(payload)
    assert md == ""


def test_root_cause_ranking_table():
    """Test root cause ranking table rendering."""
    payload = {
        "root_cause_ranking": [
            {
                "rank": 1,
                "equipment_name": "设备1",
                "root_cause_label": "轴承磨损",
                "likelihood": "high",
                "severity": "high",
                "confidence": "high",
                "is_primary": True,
            },
            {
                "rank": 2,
                "equipment_name": "设备2",
                "root_cause_label": "不平衡",
                "likelihood": "medium",
                "severity": "medium",
                "confidence": "medium",
                "is_primary": False,
            },
        ]
    }

    md = _section_root_cause_ranking(payload)

    assert "根因排序" in md
    assert "轴承磨损" in md
    assert "不平衡" in md
    assert "⭐" in md  # primary mark
    assert "| 1 " in md
    assert "| 2 " in md


def test_root_cause_ranking_empty():
    """Test root cause ranking with empty data."""
    payload = {"root_cause_ranking": []}
    md = _section_root_cause_ranking(payload)
    assert "无根因数据" in md


def test_aggregated_recommendations_by_priority():
    """Test recommendations grouped by priority."""
    payload = {
        "recommendations": [
            {
                "equipment_name": "设备1",
                "action": "更换轴承",
                "priority": "urgent",
                "rationale": "温度持续超标",
            },
            {
                "equipment_name": "设备2",
                "action": "动平衡校正",
                "priority": "important",
                "rationale": "振动异常",
            },
            {
                "equipment_name": "设备3",
                "action": "常规检查",
                "priority": "routine",
                "rationale": "",
            },
        ]
    }

    md = _section_aggregated_recommendations(payload)

    assert "维护建议" in md
    assert "🔴 紧急" in md
    assert "更换轴承" in md
    assert "温度持续超标" in md
    assert "🟡 重要" in md
    assert "动平衡校正" in md
    assert "🟢 常规" in md
    assert "常规检查" in md


def test_aggregated_recommendations_empty():
    """Test recommendations with empty data."""
    payload = {"recommendations": []}
    md = _section_aggregated_recommendations(payload)
    assert "暂无建议" in md


def test_data_quality_warnings():
    """Test data quality warnings section."""
    payload = {"data_quality": ["数据完整率低: 75%", "部分传感器离线"]}
    md = _section_data_quality(payload)
    assert "数据质量警告" in md
    assert "数据完整率低" in md
    assert "传感器离线" in md


def test_data_quality_empty():
    """Test data quality with no warnings."""
    payload = {"data_quality": []}
    md = _section_data_quality(payload)
    assert md == ""


def test_full_aggregated_report_pro():
    """Test full aggregated Pro report with all sections."""
    payload = {
        "analysis_type": "diagnosis",
        "report_meta": {
            "total_devices": 2,
            "capability_tier": "pro",
            "kind": "centrifugal_compressor",
            "rules_skill": "vibration-fault-diagnosis",
            "generated_at": "2026-05-25T10:00:00",
        },
        "capability_tier": "pro",
        "per_device": [
            {
                "equipment_id": "EQ001",
                "equipment_name": "压缩机A",
                "key_findings": [
                    {
                        "point": "bearing_temp",
                        "feature": "max_value",
                        "value": 85.2,
                        "threshold": 80.0,
                        "verdict": "exceed",
                        "severity": "high",
                    }
                ],
                "root_causes": [
                    {
                        "root_cause_id": "bearing_wear",
                        "root_cause_label": "轴承磨损",
                        "confidence": "high",
                        "likelihood": "high",
                        "severity": "high",
                    }
                ],
                "recommendations": [
                    {"action": "更换轴承", "priority": "urgent", "rationale": "温度超标"},
                ],
            },
            {
                "equipment_id": "EQ002",
                "equipment_name": "压缩机B",
                "key_findings": [
                    {
                        "point": "vibration",
                        "feature": "rms",
                        "value": 7.5,
                        "threshold": 5.0,
                        "verdict": "exceed",
                        "severity": "medium",
                    }
                ],
                "root_causes": [
                    {
                        "root_cause_id": "bearing_wear",
                        "root_cause_label": "轴承磨损",
                        "confidence": "medium",
                        "likelihood": "medium",
                        "severity": "medium",
                    }
                ],
                "recommendations": [
                    {"action": "检查轴承", "priority": "routine", "rationale": "预防性维护"},
                ],
            },
        ],
        "cross_device_correlation": {
            "correlated_root_causes": [
                {
                    "root_cause_id": "bearing_wear",
                    "root_cause_label": "轴承磨损",
                    "correlation_strength": "medium",
                    "affected_devices": [
                        {"equipment_id": "EQ001", "equipment_name": "压缩机A"},
                        {"equipment_id": "EQ002", "equipment_name": "压缩机B"},
                    ],
                    "max_severity": "high",
                    "max_likelihood": "high",
                }
            ]
        },
        "impact_assessment": {
            "affected_equipment_count": 2,
            "severity_distribution": {"critical": 0, "high": 1, "medium": 1, "low": 0},
            "estimated_downtime_hours": 8,
            "business_impact": "较大影响，建议尽快安排检修",
        },
        "root_cause_ranking": [
            {
                "rank": 1,
                "equipment_name": "压缩机A",
                "equipment_id": "EQ001",
                "root_cause_label": "轴承磨损",
                "likelihood": "high",
                "severity": "high",
                "confidence": "high",
                "is_primary": True,
            },
            {
                "rank": 2,
                "equipment_name": "压缩机B",
                "equipment_id": "EQ002",
                "root_cause_label": "轴承磨损",
                "likelihood": "medium",
                "severity": "medium",
                "confidence": "medium",
                "is_primary": False,
            },
        ],
        "recommendations": [
            {
                "equipment_name": "压缩机A",
                "action": "更换轴承",
                "priority": "urgent",
                "rationale": "温度超标",
            },
            {
                "equipment_name": "压缩机B",
                "action": "检查轴承",
                "priority": "routine",
                "rationale": "预防性维护",
            },
        ],
        "data_quality": [],
    }

    md = render_diagnosis_markdown(payload)

    # All major sections present
    assert "# 多设备故障诊断报告" in md
    assert "## 报告信息" in md
    assert "PRO" in md
    assert "## 设备诊断摘要" in md
    assert "压缩机A" in md
    assert "压缩机B" in md
    assert "## 跨设备根因关联" in md
    assert "中等关联" in md
    assert "## 影响评估" in md
    assert "8 小时" in md
    assert "## 根因排序" in md
    assert "⭐" in md
    assert "## 维护建议" in md
    assert "🔴 紧急" in md


def test_ultra_report_with_fallback():
    """Test Ultra report that fell back to Pro."""
    payload = {
        "analysis_type": "diagnosis",
        "report_meta": {"total_devices": 1, "capability_tier": "pro"},
        "capability_tier": "pro",
        "model_fallback": True,
        "per_device": [
            {
                "equipment_id": "EQ001",
                "equipment_name": "设备1",
                "key_findings": [],
                "root_causes": [],
                "recommendations": [],
            }
        ],
        "cross_device_correlation": {"correlated_root_causes": []},
        "impact_assessment": {
            "affected_equipment_count": 1,
            "severity_distribution": {},
            "estimated_downtime_hours": 0,
            "business_impact": "影响较小",
        },
        "root_cause_ranking": [],
        "recommendations": [],
    }

    md = render_diagnosis_markdown(payload)

    assert "模型回退" in md
    assert "Ultra 模型不可用" in md


def test_per_device_empty_findings():
    """Test per-device section with no findings or root causes."""
    from export_diagnosis_report import _section_per_device_summaries

    payload = {
        "per_device": [
            {
                "equipment_id": "EQ001",
                "equipment_name": "设备1",
                "key_findings": [],
                "root_causes": [],
                "recommendations": [],
            }
        ]
    }

    md = _section_per_device_summaries(payload)
    assert "设备1" in md
    assert "EQ001" in md
    # Should not crash with empty data
