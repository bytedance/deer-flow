"""Unit tests for diagnosis_report_transform.py

Run: python -m pytest tests/test_diagnosis_report_transform.py -v
"""

import json
import tempfile
from pathlib import Path

from diagnosis_report_transform import (
    aggregate_diagnosis_reports,
    build_root_cause_ranking,
    build_impact_assessment,
    build_cross_device_correlation,
)


def test_aggregate_single_device():
    """Test aggregation with a single device."""
    diagnosis_features = {
        "evidence_chain": [
            {
                "point": "bearing_temp",
                "feature": "max_value",
                "value": 85.2,
                "threshold": 80.0,
                "verdict": "exceed",
                "severity": "high",
            }
        ],
        "rule_matches": [
            {
                "rule_id": "R001",
                "root_cause_id": "bearing_wear",
                "root_cause_label": "轴承磨损",
                "confidence": "high",
                "likelihood": "high",
                "severity": "high",
                "supporting_evidence_count": 3,
                "rationale": "温度超标 + 振动异常",
            }
        ],
        "recommendations": [
            {
                "action": "更换轴承",
                "priority": "urgent",
                "rationale": "温度持续超标",
                "timeframe": "24h",
            }
        ],
        "warnings": [],
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        input_path = tmpdir / "diagnosis_features.json"
        with open(input_path, "w") as f:
            json.dump(diagnosis_features, f)

        result = aggregate_diagnosis_reports(
            inputs=[input_path],
            equipment_ids=["EQ001"],
            equipment_names=["设备1"],
            capability_tier="basic",
        )

        assert result["report_meta"]["capability_tier"] == "basic"
        assert result["report_meta"]["total_devices"] == 1
        assert len(result["per_device"]) == 1
        assert result["per_device"][0]["equipment_id"] == "EQ001"
        assert len(result["per_device"][0]["root_causes"]) == 1
        # Single device still produces a correlation entry with strength "low"
        assert len(result["cross_device_correlation"]["correlated_root_causes"]) == 1
        assert result["cross_device_correlation"]["correlated_root_causes"][0]["correlation_strength"] == "low"
        assert result["impact_assessment"]["affected_equipment_count"] == 1


def test_aggregate_multi_device():
    """Test aggregation with multiple devices."""
    diagnosis_1 = {
        "evidence_chain": [
            {
                "point": "vibration",
                "feature": "rms",
                "value": 7.5,
                "threshold": 5.0,
                "verdict": "exceed",
                "severity": "high",
            }
        ],
        "rule_matches": [
            {
                "rule_id": "R001",
                "root_cause_id": "unbalance",
                "root_cause_label": "不平衡",
                "confidence": "high",
                "likelihood": "high",
                "severity": "medium",
                "supporting_evidence_count": 2,
                "rationale": "振动超标",
            }
        ],
        "recommendations": [
            {
                "action": "动平衡校正",
                "priority": "important",
                "rationale": "振动异常",
                "timeframe": "1周",
            }
        ],
        "warnings": [],
    }

    diagnosis_2 = {
        "evidence_chain": [
            {
                "point": "bearing_temp",
                "feature": "max_value",
                "value": 82.0,
                "threshold": 80.0,
                "verdict": "marginal",
                "severity": "medium",
            }
        ],
        "rule_matches": [
            {
                "rule_id": "R002",
                "root_cause_id": "bearing_wear",
                "root_cause_label": "轴承磨损",
                "confidence": "medium",
                "likelihood": "medium",
                "severity": "medium",
                "supporting_evidence_count": 1,
                "rationale": "温度略高",
            }
        ],
        "recommendations": [
            {
                "action": "检查轴承",
                "priority": "routine",
                "rationale": "预防性维护",
                "timeframe": "1月",
            }
        ],
        "warnings": [],
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        input_1 = tmpdir / "diagnosis_1.json"
        input_2 = tmpdir / "diagnosis_2.json"
        with open(input_1, "w") as f:
            json.dump(diagnosis_1, f)
        with open(input_2, "w") as f:
            json.dump(diagnosis_2, f)

        result = aggregate_diagnosis_reports(
            inputs=[input_1, input_2],
            equipment_ids=["EQ001", "EQ002"],
            equipment_names=["设备1", "设备2"],
            capability_tier="pro",
        )

        assert result["report_meta"]["capability_tier"] == "pro"
        assert result["report_meta"]["total_devices"] == 2
        assert len(result["per_device"]) == 2
        assert len(result["root_cause_ranking"]) == 2
        assert len(result["recommendations"]) == 2


def test_cross_device_correlation():
    """Test cross-device correlation detection."""
    per_device = [
        {
            "equipment_id": "EQ001",
            "equipment_name": "设备1",
            "root_causes": [
                {
                    "root_cause_id": "bearing_wear",
                    "root_cause_label": "轴承磨损",
                    "confidence": "high",
                    "likelihood": "high",
                    "severity": "high",
                }
            ],
        },
        {
            "equipment_id": "EQ002",
            "equipment_name": "设备2",
            "root_causes": [
                {
                    "root_cause_id": "bearing_wear",
                    "root_cause_label": "轴承磨损",
                    "confidence": "medium",
                    "likelihood": "medium",
                    "severity": "medium",
                }
            ],
        },
        {
            "equipment_id": "EQ003",
            "equipment_name": "设备3",
            "root_causes": [
                {
                    "root_cause_id": "unbalance",
                    "root_cause_label": "不平衡",
                    "confidence": "low",
                    "likelihood": "low",
                    "severity": "low",
                }
            ],
        },
    ]

    correlation = build_cross_device_correlation(per_device)

    assert len(correlation["correlated_root_causes"]) == 2

    # bearing_wear affects 2 devices -> medium correlation
    bearing_corr = next(
        c for c in correlation["correlated_root_causes"] if c["root_cause_id"] == "bearing_wear"
    )
    assert bearing_corr["correlation_strength"] == "medium"
    assert len(bearing_corr["affected_devices"]) == 2
    assert bearing_corr["max_severity"] == "high"
    assert bearing_corr["max_likelihood"] == "high"

    # unbalance affects 1 device -> low correlation
    unbalance_corr = next(
        c for c in correlation["correlated_root_causes"] if c["root_cause_id"] == "unbalance"
    )
    assert unbalance_corr["correlation_strength"] == "low"
    assert len(unbalance_corr["affected_devices"]) == 1


def test_high_correlation_three_devices():
    """Test high correlation with 3+ devices."""
    per_device = [
        {
            "equipment_id": f"EQ00{i}",
            "equipment_name": f"设备{i}",
            "root_causes": [
                {
                    "root_cause_id": "lubrication_issue",
                    "root_cause_label": "润滑问题",
                    "confidence": "medium",
                    "likelihood": "medium",
                    "severity": "medium",
                }
            ],
        }
        for i in range(1, 4)
    ]

    correlation = build_cross_device_correlation(per_device)

    assert len(correlation["correlated_root_causes"]) == 1
    assert correlation["correlated_root_causes"][0]["correlation_strength"] == "high"
    assert len(correlation["correlated_root_causes"][0]["affected_devices"]) == 3


def test_root_cause_ranking():
    """Test root cause ranking by likelihood × severity."""
    per_device = [
        {
            "equipment_id": "EQ001",
            "equipment_name": "设备1",
            "root_causes": [
                {
                    "root_cause_id": "rc1",
                    "root_cause_label": "根因1",
                    "confidence": "high",
                    "likelihood": "high",  # 3
                    "severity": "medium",  # 2
                },
                {
                    "root_cause_id": "rc2",
                    "root_cause_label": "根因2",
                    "confidence": "medium",
                    "likelihood": "low",  # 1
                    "severity": "high",  # 3
                },
            ],
        },
        {
            "equipment_id": "EQ002",
            "equipment_name": "设备2",
            "root_causes": [
                {
                    "root_cause_id": "rc3",
                    "root_cause_label": "根因3",
                    "confidence": "high",
                    "likelihood": "high",  # 3
                    "severity": "high",  # 3
                },
            ],
        },
    ]

    ranking = build_root_cause_ranking(per_device)

    assert len(ranking) == 3
    # rc3: 3×3=9 (highest)
    assert ranking[0]["root_cause_id"] == "rc3"
    assert ranking[0]["is_primary"] is True
    # rc1: 3×2=6
    assert ranking[1]["root_cause_id"] == "rc1"
    # rc2: 1×3=3
    assert ranking[2]["root_cause_id"] == "rc2"


def test_impact_assessment_critical():
    """Test impact assessment with critical severity."""
    per_device = [
        {
            "equipment_id": "EQ001",
            "equipment_name": "设备1",
            "root_causes": [
                {
                    "root_cause_id": "rc1",
                    "root_cause_label": "根因1",
                    "confidence": "high",
                    "likelihood": "high",
                    "severity": "critical",
                }
            ],
        }
    ]

    impact = build_impact_assessment(per_device)

    assert impact["affected_equipment_count"] == 1
    assert impact["severity_distribution"]["critical"] == 1
    assert impact["estimated_downtime_hours"] == 24
    assert "严重" in impact["business_impact"]


def test_impact_assessment_medium():
    """Test impact assessment with medium severity."""
    per_device = [
        {
            "equipment_id": "EQ001",
            "equipment_name": "设备1",
            "root_causes": [
                {
                    "root_cause_id": "rc1",
                    "root_cause_label": "根因1",
                    "confidence": "medium",
                    "likelihood": "medium",
                    "severity": "medium",
                }
            ],
        },
        {
            "equipment_id": "EQ002",
            "equipment_name": "设备2",
            "root_causes": [],
        },
    ]

    impact = build_impact_assessment(per_device)

    assert impact["affected_equipment_count"] == 2
    assert impact["severity_distribution"]["medium"] == 1
    assert impact["estimated_downtime_hours"] == 4
    assert "中等" in impact["business_impact"]


def test_empty_inputs():
    """Test aggregation with empty inputs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        input_path = tmpdir / "empty.json"
        with open(input_path, "w") as f:
            json.dump({"evidence_chain": [], "rule_matches": [], "recommendations": [], "warnings": []}, f)

        result = aggregate_diagnosis_reports(
            inputs=[input_path],
            equipment_ids=["EQ001"],
            equipment_names=["设备1"],
            capability_tier="basic",
        )

        assert result["report_meta"]["total_devices"] == 1
        assert len(result["per_device"][0]["root_causes"]) == 0
        assert len(result["root_cause_ranking"]) == 0
        assert len(result["recommendations"]) == 0
        assert result["cross_device_correlation"]["correlated_root_causes"] == []
        assert result["cross_device_correlation"]["shared_evidence"] == []


def test_data_quality_aggregation():
    """Test that data quality warnings are aggregated."""
    diagnosis = {
        "evidence_chain": [],
        "rule_matches": [],
        "recommendations": [],
        "warnings": ["数据完整率低: 75%", "部分传感器离线"],
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        input_path = tmpdir / "diagnosis.json"
        with open(input_path, "w") as f:
            json.dump(diagnosis, f)

        result = aggregate_diagnosis_reports(
            inputs=[input_path],
            equipment_ids=["EQ001"],
            equipment_names=["设备1"],
            capability_tier="basic",
        )

        assert len(result["data_quality"]) == 2
        assert "数据完整率低" in result["data_quality"][0]


def test_model_fallback_flag():
    """Test that model_fallback flag is preserved."""
    diagnosis = {
        "evidence_chain": [],
        "rule_matches": [],
        "recommendations": [],
        "warnings": [],
        "model_fallback": True,
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        input_path = tmpdir / "diagnosis.json"
        with open(input_path, "w") as f:
            json.dump(diagnosis, f)

        result = aggregate_diagnosis_reports(
            inputs=[input_path],
            equipment_ids=["EQ001"],
            equipment_names=["设备1"],
            capability_tier="ultra",
        )

        assert result.get("model_fallback") is True
