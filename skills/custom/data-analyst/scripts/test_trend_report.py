#!/usr/bin/env python
"""Tests for trend report transform and export.

Run: python -m pytest skills/custom/data-analyst/scripts/test_trend_report.py -v
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))


# ── trend_report_transform.py ──


def _sample_analysis(capability_tier: str = "basic") -> dict:
    """Generate a sample trend analysis result."""
    analysis: dict = {
        "findings": [
            {
                "metric": "vibration_level",
                "direction": "increasing",
                "slope": 0.12,
                "volatility": 0.03,
                "confidence": 0.85,
                "severity": "warning",
                "description": "振动烈度呈上升趋势",
            },
            {
                "metric": "temperature",
                "direction": "stable",
                "slope": 0.01,
                "volatility": 0.02,
                "confidence": 0.90,
                "severity": "info",
                "description": "温度稳定",
            },
        ],
        "evidence": [
            {"timestamp": "2026-05-20", "value": 5.2},
            {"timestamp": "2026-05-21", "value": 5.4},
        ],
    }

    if capability_tier in ("pro", "ultra"):
        analysis["models"] = [
            {"name": "linear", "r2_adj": 0.85, "selected": True},
            {"name": "polynomial", "r2_adj": 0.82, "selected": False},
        ]
        analysis["stl_decomposition"] = {
            "trend_strength": 0.75,
            "seasonal_strength": 0.15,
            "residual_description": "随机分布",
        }
        analysis["changepoints"] = [
            {"timestamp": "2026-05-15", "slope_before": 0.05, "slope_after": 0.12, "delta": 0.07}
        ]
        analysis["confidence_band"] = {"lower": 3.5, "upper": 7.2}

    if capability_tier == "ultra":
        analysis["forecast_lstm"] = [5.8, 6.0, 6.2, 6.4, 6.6, 6.8, 7.0]
        analysis["confidence_80"] = [
            {"lower": 5.5, "upper": 6.1},
            {"lower": 5.6, "upper": 6.4},
            {"lower": 5.7, "upper": 6.7},
            {"lower": 5.8, "upper": 7.0},
            {"lower": 5.9, "upper": 7.3},
            {"lower": 6.0, "upper": 7.6},
            {"lower": 6.1, "upper": 7.9},
        ]
        analysis["confidence_95"] = [
            {"lower": 5.2, "upper": 6.4},
            {"lower": 5.2, "upper": 6.8},
            {"lower": 5.2, "upper": 7.2},
            {"lower": 5.2, "upper": 7.6},
            {"lower": 5.2, "upper": 8.0},
            {"lower": 5.2, "upper": 8.4},
            {"lower": 5.2, "upper": 8.8},
        ]
        analysis["co_trending_groups"] = [
            {"group_id": "G1", "members": ["EQ-001", "EQ-002"], "direction": "increasing"}
        ]
        analysis["adaptive_threshold"] = {
            "vibration_level": {"warning": 6.5, "critical": 8.0, "rationale": "P95 历史分位数"}
        }

    return analysis


def _sample_trend_data() -> dict:
    return {
        "time_series": [
            {
                "metric_key": "vibration_level",
                "values": [4.5, 4.8, 5.0, 5.2, 5.5],
                "timestamps": ["2026-05-19", "2026-05-20", "2026-05-21", "2026-05-22", "2026-05-23"],
            }
        ]
    }


class TestTrendReportTransform:
    """Tests for trend_report_transform.py."""

    def test_extract_device_summary_basic(self):
        from trend_report_transform import _extract_device_summary

        analysis = _sample_analysis("basic")
        result = _extract_device_summary(analysis, "EQ-001", "Pump-1", "basic")

        assert result["equipment_id"] == "EQ-001"
        assert result["equipment_name"] == "Pump-1"
        assert result["capability_tier"] == "basic"
        assert len(result["metrics_summary"]) == 2
        assert result["findings_count"] == 2
        assert "models" not in result  # Basic has no Pro fields

    def test_extract_device_summary_pro(self):
        from trend_report_transform import _extract_device_summary

        analysis = _sample_analysis("pro")
        result = _extract_device_summary(analysis, "EQ-001", "Pump-1", "pro")

        assert "models" in result
        assert len(result["models"]) == 2
        assert "stl_decomposition" in result
        assert result["stl_decomposition"]["trend_strength"] == 0.75
        assert "changepoints" in result
        assert "confidence_band" in result

    def test_extract_device_summary_ultra(self):
        from trend_report_transform import _extract_device_summary

        analysis = _sample_analysis("ultra")
        result = _extract_device_summary(analysis, "EQ-001", "Pump-1", "ultra")

        assert "forecast_lstm" in result
        assert len(result["forecast_lstm"]) == 7
        assert "co_trending_groups" in result
        assert "adaptive_threshold" in result

    def test_cross_device_summary_degradation_priority(self):
        from trend_report_transform import _build_cross_device_summary

        per_device = [
            {
                "equipment_id": "EQ-001",
                "equipment_name": "Pump-1",
                "metrics_summary": [
                    {"metric_key": "vibration_level", "direction": "increasing", "slope": 0.15, "volatility": 0.03},
                ],
            },
            {
                "equipment_id": "EQ-002",
                "equipment_name": "Pump-2",
                "metrics_summary": [
                    {"metric_key": "vibration_level", "direction": "increasing", "slope": 0.08, "volatility": 0.02},
                ],
            },
        ]
        result = _build_cross_device_summary(per_device)

        assert result["total_devices"] == 2
        assert len(result["degradation_priority"]) == 2
        # Higher slope should be first
        assert result["degradation_priority"][0]["slope"] > result["degradation_priority"][1]["slope"]

    def test_comparison_summary_wow(self):
        from trend_report_transform import _build_comparison_summary

        current = _sample_trend_data()
        compare = {
            "time_series": [
                {"metric_key": "vibration_level", "values": [4.0, 4.1, 4.2, 4.3, 4.4]},
            ]
        }
        result = _build_comparison_summary(current, compare, "wow")

        assert result["mode"] == "wow"
        assert result["mode_label"] == "环比"
        assert len(result["metrics"]) == 1
        assert result["metrics"][0]["change_pct"] > 0  # Current avg > compare avg

    def test_comparison_summary_none(self):
        from trend_report_transform import _build_comparison_summary

        current = _sample_trend_data()
        result = _build_comparison_summary(current, None, "none")
        assert result == {}

    def test_degradation_alerts(self):
        from trend_report_transform import _build_degradation_alerts

        per_device = [
            {
                "equipment_id": "EQ-001",
                "equipment_name": "Pump-1",
                "metrics_summary": [
                    {"metric_key": "vibration_level", "direction": "increasing", "slope": 0.15, "confidence": 0.85},
                    {"metric_key": "temperature", "direction": "stable", "slope": 0.01, "confidence": 0.90},
                ],
            },
        ]
        alerts = _build_degradation_alerts(per_device)

        # Only increasing with slope > 0.05 should appear
        assert len(alerts) == 1
        assert alerts[0]["metric_key"] == "vibration_level"
        assert alerts[0]["severity"] == "critical"  # slope > 0.1

    def test_recommendations(self):
        from trend_report_transform import _build_recommendations

        alerts = [
            {"equipment_id": "EQ-001", "equipment_name": "Pump-1", "metric_key": "vibration_level", "severity": "critical"},
            {"equipment_id": "EQ-002", "equipment_name": "Compressor-1", "metric_key": "temperature", "severity": "warning"},
        ]
        recs = _build_recommendations(alerts, "pro")

        assert len(recs) == 2
        assert recs[0]["priority"] == "urgent"
        assert "振动" in recs[0]["action"]
        assert recs[1]["priority"] == "important"
        assert "润滑" in recs[1]["action"]


# ── export_report.py render_trend_markdown() ──


class TestRenderTrendMarkdown:
    """Tests for render_trend_markdown() in export_report.py."""

    def test_basic_single_device(self):
        from export_report import render_trend_markdown

        payload = {
            "analysis_type": "trend",
            "capability_tier": "basic",
            "per_device": [
                {
                    "equipment_id": "EQ-001",
                    "equipment_name": "Pump-1",
                    "capability_tier": "basic",
                    "metrics_summary": [
                        {"metric_key": "vibration_level", "direction": "increasing", "slope": 0.12, "volatility": 0.03, "confidence": 0.85, "severity": "warning", "description": "振动上升"},
                    ],
                    "findings_count": 1,
                }
            ],
            "cross_device_summary": {"degradation_priority": [], "total_devices": 1},
            "comparison_summary": {},
            "degradation_alerts": [
                {"equipment_name": "Pump-1", "metric_key": "vibration_level", "slope": 0.12, "confidence": 0.85, "severity": "critical"},
            ],
            "forecasts": [],
            "recommendations": [
                {"priority": "urgent", "action": "检查轴承"},
            ],
            "data_quality": [],
        }

        md = render_trend_markdown(payload)
        assert "# 趋势分析报告" in md
        assert "Basic" in md
        assert "执行摘要" in md
        assert "Pump-1" in md
        assert "劣化预警" in md
        assert "维护建议" in md
        assert "检查轴承" in md

    def test_pro_multi_device(self):
        from export_report import render_trend_markdown

        payload = {
            "analysis_type": "trend",
            "capability_tier": "pro",
            "per_device": [
                {
                    "equipment_id": "EQ-001",
                    "equipment_name": "Pump-1",
                    "capability_tier": "pro",
                    "metrics_summary": [
                        {"metric_key": "vibration_level", "direction": "increasing", "slope": 0.12, "volatility": 0.03, "confidence": 0.85, "severity": "warning", "description": ""},
                    ],
                    "models": [{"name": "linear", "r2_adj": 0.85, "selected": True}],
                    "stl_decomposition": {"trend_strength": 0.75, "seasonal_strength": 0.15, "residual_description": "随机"},
                    "changepoints": [{"timestamp": "2026-05-15", "slope_before": 0.05, "slope_after": 0.12, "delta": 0.07}],
                    "confidence_band": {"lower": 3.5, "upper": 7.2},
                    "findings_count": 1,
                },
                {
                    "equipment_id": "EQ-002",
                    "equipment_name": "Pump-2",
                    "capability_tier": "pro",
                    "metrics_summary": [
                        {"metric_key": "vibration_level", "direction": "stable", "slope": 0.01, "volatility": 0.02, "confidence": 0.90, "severity": "info", "description": ""},
                    ],
                    "models": [],
                    "stl_decomposition": {},
                    "changepoints": [],
                    "confidence_band": {},
                    "findings_count": 1,
                },
            ],
            "cross_device_summary": {
                "degradation_priority": [
                    {"priority": "high", "equipment_name": "Pump-1", "metric_key": "vibration_level", "slope": 0.12},
                ],
                "total_devices": 2,
            },
            "comparison_summary": {},
            "degradation_alerts": [],
            "forecasts": [],
            "recommendations": [],
            "data_quality": [],
        }

        md = render_trend_markdown(payload)
        assert "Pro" in md
        assert "横向对比" in md
        assert "多模型拟合对比" in md
        assert "STL 分解" in md
        assert "PELT 变点检测" in md
        assert "95% 置信区间" in md

    def test_ultra_with_lstm(self):
        from export_report import render_trend_markdown

        payload = {
            "analysis_type": "trend",
            "capability_tier": "ultra",
            "per_device": [
                {
                    "equipment_id": "EQ-001",
                    "equipment_name": "Pump-1",
                    "capability_tier": "ultra",
                    "metrics_summary": [
                        {"metric_key": "vibration_level", "direction": "increasing", "slope": 0.12, "volatility": 0.03, "confidence": 0.55, "severity": "warning", "description": ""},
                    ],
                    "models": [],
                    "stl_decomposition": {},
                    "changepoints": [],
                    "confidence_band": {},
                    "forecast_lstm": [5.8, 6.0, 6.2],
                    "confidence_80": [{"lower": 5.5, "upper": 6.1}],
                    "confidence_95": [{"lower": 5.2, "upper": 6.4}],
                    "co_trending_groups": [{"group_id": "G1", "members": ["EQ-001"], "direction": "increasing"}],
                    "adaptive_threshold": {"vibration_level": {"warning": 6.5, "critical": 8.0, "rationale": "P95"}},
                    "findings_count": 1,
                },
            ],
            "cross_device_summary": {"degradation_priority": [], "total_devices": 1},
            "comparison_summary": {},
            "degradation_alerts": [],
            "forecasts": [],
            "recommendations": [],
            "data_quality": [],
        }

        md = render_trend_markdown(payload)
        assert "Ultra" in md
        assert "LSTM 预测值" in md
        assert "协变组" in md
        assert "自适应阈值推荐" in md

    def test_ultra_low_confidence_warning(self):
        from export_report import render_trend_markdown

        payload = {
            "analysis_type": "trend",
            "capability_tier": "ultra",
            "per_device": [
                {
                    "equipment_id": "EQ-001",
                    "equipment_name": "Pump-1",
                    "capability_tier": "ultra",
                    "metrics_summary": [
                        {"metric_key": "vibration_level", "direction": "stable", "slope": 0.01, "volatility": 0.02, "confidence": 0.45, "severity": "info", "description": ""},
                    ],
                    "findings_count": 1,
                },
            ],
            "cross_device_summary": {"degradation_priority": [], "total_devices": 1},
            "comparison_summary": {},
            "degradation_alerts": [],
            "forecasts": [],
            "recommendations": [],
            "data_quality": [],
        }

        md = render_trend_markdown(payload)
        assert "置信度低于 0.6" in md

    def test_comparison_wow(self):
        from export_report import render_trend_markdown

        payload = {
            "analysis_type": "trend",
            "capability_tier": "pro",
            "per_device": [],
            "cross_device_summary": {"degradation_priority": [], "total_devices": 1},
            "comparison_summary": {
                "mode": "wow",
                "mode_label": "环比",
                "metrics": [
                    {"metric_key": "vibration_level", "current_avg": 5.5, "compare_avg": 4.8, "change_pct": 14.6, "trend": "上升"},
                ],
            },
            "degradation_alerts": [],
            "forecasts": [],
            "recommendations": [],
            "data_quality": [],
        }

        md = render_trend_markdown(payload)
        assert "环比对比分析" in md
        assert "14.6%" in md or "+14.6%" in md

    def test_empty_findings(self):
        from export_report import render_trend_markdown

        payload = {
            "analysis_type": "trend",
            "capability_tier": "basic",
            "per_device": [
                {
                    "equipment_id": "EQ-001",
                    "equipment_name": "Pump-1",
                    "capability_tier": "basic",
                    "metrics_summary": [
                        {"metric_key": "temperature", "direction": "stable", "slope": 0.0, "volatility": 0.01, "confidence": 0.95, "severity": "info", "description": ""},
                    ],
                    "findings_count": 0,
                },
            ],
            "cross_device_summary": {"degradation_priority": [], "total_devices": 1},
            "comparison_summary": {},
            "degradation_alerts": [],
            "forecasts": [],
            "recommendations": [],
            "data_quality": [],
        }

        md = render_trend_markdown(payload)
        assert "# 趋势分析报告" in md
        # No degradation alerts section when empty
        assert "劣化预警" not in md

    def test_model_fallback_label(self):
        from export_report import render_trend_markdown

        payload = {
            "analysis_type": "trend",
            "capability_tier": "ultra",
            "model_fallback": True,
            "per_device": [],
            "cross_device_summary": {"degradation_priority": [], "total_devices": 0},
            "comparison_summary": {},
            "degradation_alerts": [],
            "forecasts": [],
            "recommendations": [],
            "data_quality": [],
        }

        md = render_trend_markdown(payload)
        assert "模型回退" in md

    def test_schedule_label(self):
        from export_report import render_trend_markdown

        payload = {
            "analysis_type": "trend",
            "capability_tier": "pro",
            "schedule_label": "定时 · weekly · 2026-05-26",
            "per_device": [],
            "cross_device_summary": {"degradation_priority": [], "total_devices": 0},
            "comparison_summary": {},
            "degradation_alerts": [],
            "forecasts": [],
            "recommendations": [],
            "data_quality": [],
        }

        md = render_trend_markdown(payload)
        assert "定时 · weekly · 2026-05-26" in md


class TestWriteReportTrend:
    """Tests for write_report() with trend type."""

    def test_trend_type_registered(self):
        from export_report import SUPPORTED_REPORT_TYPES

        assert "trend" in SUPPORTED_REPORT_TYPES

    def test_output_dir_trend(self, tmp_path, monkeypatch):
        from export_report import _output_dir

        monkeypatch.setenv("TREND_REPORT_OUTPUT_DIR", str(tmp_path))
        result = _output_dir("trend")
        assert result == tmp_path

    def test_output_dir_trend_fallback(self, tmp_path, monkeypatch):
        from export_report import _output_dir

        monkeypatch.delenv("TREND_REPORT_OUTPUT_DIR", raising=False)
        monkeypatch.setenv("DAILY_REPORT_OUTPUT_DIR", str(tmp_path))
        result = _output_dir("trend")
        assert result == tmp_path

    def test_write_report_trend_md(self, tmp_path):
        from export_report import write_report

        payload = {
            "analysis_type": "trend",
            "capability_tier": "basic",
            "per_device": [],
            "cross_device_summary": {"degradation_priority": [], "total_devices": 0},
            "comparison_summary": {},
            "degradation_alerts": [],
            "forecasts": [],
            "recommendations": [],
            "data_quality": [],
        }

        out = write_report(payload, "md", path=tmp_path / "trend_report.md", report_type="trend")
        assert out.exists()
        content = out.read_text(encoding="utf-8")
        assert "# 趋势分析报告" in content
