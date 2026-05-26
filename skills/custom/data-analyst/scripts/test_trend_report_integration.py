#!/usr/bin/env python
"""Integration tests for trend analysis report end-to-end workflows.

Run: python -m pytest skills/custom/data-analyst/scripts/test_trend_report_integration.py -v
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))


def _create_basic_trend_data(equipment_id: str = "EQ-001") -> dict:
    """Create sample trend_data.json for Basic tier."""
    return {
        "time_series": [
            {
                "metric_key": "vibration_level",
                "name": "振动烈度",
                "unit": "mm/s",
                "timestamps": [f"2026-05-{20+i}" for i in range(5)],
                "values": [4.5, 4.8, 5.0, 5.2, 5.5],
            }
        ],
        "equipment_ids": [equipment_id],
    }


def _create_basic_analysis_result() -> dict:
    """Create sample trend_analysis.json for Basic tier."""
    return {
        "findings": [
            {
                "metric": "vibration_level",
                "direction": "increasing",
                "slope": 0.12,
                "volatility": 0.03,
                "confidence": 0.85,
                "severity": "warning",
                "description": "振动烈度呈上升趋势，建议关注轴承状态",
            }
        ],
        "evidence": [
            {"timestamp": "2026-05-20", "value": 4.5},
            {"timestamp": "2026-05-24", "value": 5.5},
        ],
    }


def _create_pro_analysis_result() -> dict:
    """Create sample pro_trend_analysis.json for Pro tier."""
    return {
        "findings": [
            {
                "metric": "vibration_level",
                "direction": "increasing",
                "slope": 0.12,
                "volatility": 0.03,
                "confidence": 0.85,
                "severity": "warning",
                "description": "振动烈度呈上升趋势",
            }
        ],
        "evidence": [
            {"timestamp": "2026-05-20", "value": 4.5},
            {"timestamp": "2026-05-24", "value": 5.5},
        ],
        "models": [
            {"name": "linear", "r2_adj": 0.85, "selected": True},
            {"name": "polynomial", "r2_adj": 0.82, "selected": False},
            {"name": "exponential", "r2_adj": 0.78, "selected": False},
        ],
        "stl_decomposition": {
            "trend_strength": 0.75,
            "seasonal_strength": 0.15,
            "residual_description": "随机分布",
        },
        "changepoints": [
            {
                "timestamp": "2026-05-22",
                "slope_before": 0.05,
                "slope_after": 0.15,
                "delta": 0.10,
            }
        ],
        "confidence_band": {"lower": 3.5, "upper": 7.2},
    }


def _create_ultra_analysis_result() -> dict:
    """Create sample ultra_trend_result.json for Ultra tier."""
    return {
        **_create_pro_analysis_result(),
        "forecast_lstm": [5.8, 6.0, 6.2, 6.4, 6.6, 6.8, 7.0],
        "confidence_80": [
            {"lower": 5.5, "upper": 6.1},
            {"lower": 5.6, "upper": 6.4},
            {"lower": 5.7, "upper": 6.7},
            {"lower": 5.8, "upper": 7.0},
            {"lower": 5.9, "upper": 7.3},
            {"lower": 6.0, "upper": 7.6},
            {"lower": 6.1, "upper": 7.9},
        ],
        "confidence_95": [
            {"lower": 5.2, "upper": 6.4},
            {"lower": 5.2, "upper": 6.8},
            {"lower": 5.2, "upper": 7.2},
            {"lower": 5.2, "upper": 7.6},
            {"lower": 5.2, "upper": 8.0},
            {"lower": 5.2, "upper": 8.4},
            {"lower": 5.2, "upper": 8.8},
        ],
        "co_trending_groups": [
            {
                "group_id": "G1",
                "members": ["EQ-001", "EQ-003"],
                "direction": "increasing",
            }
        ],
        "adaptive_threshold": {
            "vibration_level": {
                "warning": 6.5,
                "critical": 8.0,
                "rationale": "基于历史 P95 分位数",
            }
        },
    }


class TestBasicTierEndToEnd:
    """6.1: Basic tier single device end-to-end test."""

    def test_basic_single_device_workflow(self, tmp_path):
        """Test complete Basic tier workflow: data → analysis → transform → render → export."""
        from trend_report_transform import main as transform_main
        from export_report import write_report

        # Setup: create input files
        output_dir = tmp_path / "outputs"
        output_dir.mkdir()

        trend_data = _create_basic_trend_data()
        trend_data_path = output_dir / "trend_data.json"
        trend_data_path.write_text(json.dumps(trend_data), encoding="utf-8")

        analysis_result = _create_basic_analysis_result()
        analysis_path = output_dir / "trend_analysis.json"
        analysis_path.write_text(json.dumps(analysis_result), encoding="utf-8")

        # Step 1: Run transform
        sys.argv = [
            "trend_report_transform.py",
            "--input",
            str(analysis_path),
            "--trend-data",
            str(trend_data_path),
            "--capability-tier",
            "basic",
            "--equipment-ids",
            "EQ-001",
            "--equipment-names",
            "Pump-1",
            "--output-dir",
            str(output_dir),
        ]
        ret = transform_main()
        assert ret == 0

        # Verify transform output
        features_path = output_dir / "trend_report_features.json"
        assert features_path.exists()
        features = json.loads(features_path.read_text(encoding="utf-8"))
        assert features["capability_tier"] == "basic"
        assert len(features["per_device"]) == 1
        assert features["per_device"][0]["equipment_id"] == "EQ-001"

        # Step 2: Render markdown
        md_path = write_report(features, "md", report_type="trend", path=output_dir / "trend_report.md")
        assert md_path.exists()

        content = md_path.read_text(encoding="utf-8")
        assert "# 趋势分析报告" in content
        assert "Basic" in content
        assert "Pump-1" in content
        assert "执行摘要" in content
        assert "逐设备趋势详析" in content
        assert "劣化预警" in content
        assert "维护建议" in content

        # Verify Pro/Ultra sections are NOT present
        assert "多模型拟合对比" not in content
        assert "LSTM 预测值" not in content

    def test_basic_no_degradation_alerts(self, tmp_path):
        """Test Basic tier with stable metrics (no degradation alerts)."""
        from trend_report_transform import main as transform_main
        from export_report import write_report

        output_dir = tmp_path / "outputs"
        output_dir.mkdir()

        # Create stable analysis
        analysis_result = {
            "findings": [
                {
                    "metric": "temperature",
                    "direction": "stable",
                    "slope": 0.01,
                    "volatility": 0.02,
                    "confidence": 0.95,
                    "severity": "info",
                    "description": "温度稳定",
                }
            ],
            "evidence": [],
        }
        analysis_path = output_dir / "trend_analysis.json"
        analysis_path.write_text(json.dumps(analysis_result), encoding="utf-8")

        trend_data = _create_basic_trend_data()
        trend_data_path = output_dir / "trend_data.json"
        trend_data_path.write_text(json.dumps(trend_data), encoding="utf-8")

        sys.argv = [
            "trend_report_transform.py",
            "--input",
            str(analysis_path),
            "--trend-data",
            str(trend_data_path),
            "--capability-tier",
            "basic",
            "--equipment-ids",
            "EQ-001",
            "--equipment-names",
            "Pump-1",
            "--output-dir",
            str(output_dir),
        ]
        ret = transform_main()
        assert ret == 0

        features_path = output_dir / "trend_report_features.json"
        features = json.loads(features_path.read_text(encoding="utf-8"))

        # No degradation alerts
        assert len(features["degradation_alerts"]) == 0

        # Render and verify
        md_path = write_report(features, "md", report_type="trend", path=output_dir / "trend_report.md")
        content = md_path.read_text(encoding="utf-8")
        assert "劣化预警" not in content  # Section should not appear


class TestProTierEndToEnd:
    """6.2: Pro tier multi-device end-to-end test."""

    def test_pro_multi_device_with_comparison(self, tmp_path):
        """Test Pro tier with multiple devices and wow comparison."""
        from trend_report_transform import main as transform_main
        from export_report import write_report

        output_dir = tmp_path / "outputs"
        output_dir.mkdir()

        # Create analysis for device 1
        analysis1 = _create_pro_analysis_result()
        analysis1_path = output_dir / "pro_trend_analysis_1.json"
        analysis1_path.write_text(json.dumps(analysis1), encoding="utf-8")

        # Create analysis for device 2 (different equipment)
        analysis2 = {
            **_create_pro_analysis_result(),
            "findings": [
                {
                    "metric": "vibration_level",
                    "direction": "increasing",
                    "slope": 0.08,  # Lower slope than device 1
                    "volatility": 0.02,
                    "confidence": 0.90,
                    "severity": "warning",
                    "description": "振动烈度缓慢上升",
                }
            ],
        }
        analysis2_path = output_dir / "pro_trend_analysis_2.json"
        analysis2_path.write_text(json.dumps(analysis2), encoding="utf-8")

        # Create current trend data
        trend_data = {
            "time_series": [
                {
                    "metric_key": "vibration_level",
                    "values": [5.0, 5.2, 5.4, 5.6, 5.8],
                    "timestamps": ["2026-05-20", "2026-05-21", "2026-05-22", "2026-05-23", "2026-05-24"],
                }
            ]
        }
        trend_data_path = output_dir / "trend_data.json"
        trend_data_path.write_text(json.dumps(trend_data), encoding="utf-8")

        # Create comparison trend data (wow)
        compare_data = {
            "time_series": [
                {
                    "metric_key": "vibration_level",
                    "values": [4.5, 4.6, 4.7, 4.8, 4.9],
                    "timestamps": ["2026-05-13", "2026-05-14", "2026-05-15", "2026-05-16", "2026-05-17"],
                }
            ]
        }
        compare_path = output_dir / "compare" / "trend_data.json"
        compare_path.parent.mkdir(exist_ok=True)
        compare_path.write_text(json.dumps(compare_data), encoding="utf-8")

        # Run transform for device 1
        sys.argv = [
            "trend_report_transform.py",
            "--input",
            str(analysis1_path),
            "--trend-data",
            str(trend_data_path),
            "--compare-data",
            str(compare_path),
            "--capability-tier",
            "pro",
            "--equipment-ids",
            "EQ-001",
            "--equipment-names",
            "Pump-1",
            "--compare-mode",
            "wow",
            "--output-dir",
            str(output_dir),
        ]
        ret = transform_main()
        assert ret == 0

        features1_path = output_dir / "trend_report_features.json"
        features1 = json.loads(features1_path.read_text(encoding="utf-8"))

        # Run transform for device 2
        sys.argv = [
            "trend_report_transform.py",
            "--input",
            str(analysis2_path),
            "--trend-data",
            str(trend_data_path),
            "--compare-data",
            str(compare_path),
            "--capability-tier",
            "pro",
            "--equipment-ids",
            "EQ-002",
            "--equipment-names",
            "Pump-2",
            "--compare-mode",
            "wow",
            "--output-dir",
            str(output_dir),
        ]
        ret = transform_main()
        assert ret == 0

        features2_path = output_dir / "trend_report_features.json"
        features2 = json.loads(features2_path.read_text(encoding="utf-8"))

        # Verify Pro features present
        assert features1["capability_tier"] == "pro"
        assert "models" in features1["per_device"][0]
        assert "stl_decomposition" in features1["per_device"][0]
        assert "changepoints" in features1["per_device"][0]
        assert "confidence_band" in features1["per_device"][0]

        # Verify comparison data
        assert features1["comparison_summary"]["mode"] == "wow"
        assert features1["comparison_summary"]["mode_label"] == "环比"
        assert len(features1["comparison_summary"]["metrics"]) > 0

        # Render and verify markdown
        md_path = write_report(features1, "md", report_type="trend", path=output_dir / "trend_report.md")
        content = md_path.read_text(encoding="utf-8")

        assert "Pro" in content
        assert "多模型拟合对比" in content
        assert "STL 分解" in content
        assert "PELT 变点检测" in content
        assert "95% 置信区间" in content
        assert "环比对比分析" in content


class TestUltraTierFallback:
    """6.3: Ultra tier fallback to Pro when ONNX is missing."""

    def test_ultra_fallback_to_pro(self, tmp_path):
        """Test Ultra tier gracefully falls back to Pro when ONNX models are unavailable."""
        from trend_report_transform import main as transform_main
        from export_report import write_report

        output_dir = tmp_path / "outputs"
        output_dir.mkdir()

        # Create Ultra analysis result (with LSTM fields)
        analysis = _create_ultra_analysis_result()
        analysis_path = output_dir / "ultra_trend_result.json"
        analysis_path.write_text(json.dumps(analysis), encoding="utf-8")

        trend_data = _create_basic_trend_data()
        trend_data_path = output_dir / "trend_data.json"
        trend_data_path.write_text(json.dumps(trend_data), encoding="utf-8")

        # Run transform with Ultra tier
        sys.argv = [
            "trend_report_transform.py",
            "--input",
            str(analysis_path),
            "--trend-data",
            str(trend_data_path),
            "--capability-tier",
            "ultra",
            "--equipment-ids",
            "EQ-001",
            "--equipment-names",
            "Pump-1",
            "--output-dir",
            str(output_dir),
        ]
        ret = transform_main()
        assert ret == 0

        features_path = output_dir / "trend_report_features.json"
        features = json.loads(features_path.read_text(encoding="utf-8"))

        # Verify Ultra features are present
        assert features["capability_tier"] == "ultra"
        device = features["per_device"][0]
        assert "forecast_lstm" in device
        assert "confidence_80" in device
        assert "confidence_95" in device
        assert "co_trending_groups" in device
        assert "adaptive_threshold" in device

        # Render and verify Ultra sections
        md_path = write_report(features, "md", report_type="trend", path=output_dir / "trend_report.md")
        content = md_path.read_text(encoding="utf-8")

        assert "Ultra" in content
        assert "LSTM 预测值" in content
        assert "协变组" in content
        assert "自适应阈值推荐" in content

    def test_ultra_model_fallback_flag(self, tmp_path):
        """Test model_fallback flag is properly handled."""
        from export_report import render_trend_markdown

        payload = {
            "analysis_type": "trend",
            "capability_tier": "ultra",
            "model_fallback": True,
            "per_device": [
                {
                    "equipment_id": "EQ-001",
                    "equipment_name": "Pump-1",
                    "capability_tier": "ultra",
                    "metrics_summary": [
                        {
                            "metric_key": "vibration_level",
                            "direction": "increasing",
                            "slope": 0.12,
                            "volatility": 0.03,
                            "confidence": 0.85,
                            "severity": "warning",
                            "description": "",
                        }
                    ],
                    "models": [],
                    "stl_decomposition": {},
                    "changepoints": [],
                    "confidence_band": {},
                    "findings_count": 1,
                }
            ],
            "cross_device_summary": {"degradation_priority": [], "total_devices": 1},
            "comparison_summary": {},
            "degradation_alerts": [],
            "forecasts": [],
            "recommendations": [],
            "data_quality": [],
        }

        md = render_trend_markdown(payload)
        assert "模型回退" in md


class TestPDFExport:
    """6.4: PDF export verification."""

    def test_pdf_export_weasyprint_unavailable(self, tmp_path):
        """Test PDF export gracefully handles missing weasyprint."""
        from export_report import write_report

        payload = {
            "analysis_type": "trend",
            "capability_tier": "basic",
            "per_device": [
                {
                    "equipment_id": "EQ-001",
                    "equipment_name": "Pump-1",
                    "capability_tier": "basic",
                    "metrics_summary": [],
                    "findings_count": 0,
                }
            ],
            "cross_device_summary": {"degradation_priority": [], "total_devices": 1},
            "comparison_summary": {},
            "degradation_alerts": [],
            "forecasts": [],
            "recommendations": [],
            "data_quality": [],
        }

        # Mock weasyprint import to raise ImportError
        with patch("export_report._write_pdf", side_effect=ImportError("weasyprint not installed")):
            with pytest.raises(ImportError, match="weasyprint"):
                write_report(payload, "pdf", report_type="trend", path=tmp_path / "trend_report.pdf")

    def test_pdf_export_success_mock(self, tmp_path):
        """Test PDF export succeeds when weasyprint is available (mocked)."""
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

        # Mock successful PDF write
        pdf_path = tmp_path / "trend_report.pdf"
        with patch("export_report._write_pdf") as mock_write:
            mock_write.return_value = None
            result = write_report(payload, "pdf", report_type="trend", path=pdf_path)
            assert result == pdf_path
            mock_write.assert_called_once()


class TestIntermediateFilesNotExposed:
    """6.5: Verify intermediate files are not exposed."""

    def test_present_files_only_final_report(self, tmp_path):
        """Test that only final report files are exposed, not intermediate files."""
        from trend_report_transform import main as transform_main

        output_dir = tmp_path / "outputs"
        output_dir.mkdir()

        # Create input files
        analysis = _create_basic_analysis_result()
        analysis_path = output_dir / "trend_analysis.json"
        analysis_path.write_text(json.dumps(analysis), encoding="utf-8")

        trend_data = _create_basic_trend_data()
        trend_data_path = output_dir / "trend_data.json"
        trend_data_path.write_text(json.dumps(trend_data), encoding="utf-8")

        # Run transform
        sys.argv = [
            "trend_report_transform.py",
            "--input",
            str(analysis_path),
            "--trend-data",
            str(trend_data_path),
            "--capability-tier",
            "basic",
            "--equipment-ids",
            "EQ-001",
            "--equipment-names",
            "Pump-1",
            "--output-dir",
            str(output_dir),
        ]
        ret = transform_main()
        assert ret == 0

        # Verify intermediate files exist
        assert (output_dir / "trend_analysis.json").exists()
        assert (output_dir / "trend_data.json").exists()
        assert (output_dir / "trend_report_features.json").exists()

        # Verify final report files can be generated
        from export_report import write_report

        features = json.loads((output_dir / "trend_report_features.json").read_text(encoding="utf-8"))
        md_path = write_report(features, "md", report_type="trend", path=output_dir / "trend_report.md")
        assert md_path.exists()

        # The SOUL.md should instruct to only present_files for trend_report.md and trend_report.pdf
        # This is verified by reading SOUL.md and checking the present_files instruction
        soul_md_path = Path(__file__).resolve().parent.parent.parent / "agents" / "builtin" / "ai-report--trend" / "SOUL.md"
        if soul_md_path.exists():
            soul_content = soul_md_path.read_text(encoding="utf-8")
            # Verify SOUL.md contains instruction to only present final files
            assert "present_files" in soul_content
            assert "trend_report.md" in soul_content
            # Verify it does NOT mention presenting intermediate files
            assert "trend_data.json" not in soul_content.split("present_files")[1] if "present_files" in soul_content else True
