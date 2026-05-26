"""Integration tests for the diagnosis report pipeline.

Tests that exercise the data flow from diagnosis_report_transform
through render_diagnosis_markdown, and verify the diagnosis_kind_config.

Run: python -m pytest tests/test_diagnosis_integration.py -v
"""

import json
import tempfile
from pathlib import Path

import yaml

from diagnosis_report_transform import aggregate_diagnosis_reports
from export_diagnosis_report import render_diagnosis_markdown


def _load_kind_config() -> dict:
    config_path = Path(__file__).parent.parent.parent / "diagnosis_kind_config.yaml"
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


class TestDiagnosisKindConfig:
    """Task 7.8: Verify device type configuration."""

    def test_all_kinds_have_required_fields(self):
        config = _load_kind_config()
        kinds = config["kinds"]

        for kind_name, kind_config in kinds.items():
            assert "rules_skill" in kind_config, f"{kind_name} missing rules_skill"
            assert "family" in kind_config, f"{kind_name} missing family"
            assert "focus_codes" in kind_config, f"{kind_name} missing focus_codes"
            assert "viz_templates" in kind_config, f"{kind_name} missing viz_templates"
            assert isinstance(kind_config["focus_codes"], list)
            assert isinstance(kind_config["viz_templates"], list)
            assert len(kind_config["focus_codes"]) > 0
            assert len(kind_config["viz_templates"]) > 0

    def test_rules_skill_maps_to_valid_agents(self):
        config = _load_kind_config()
        valid_rules = {
            "vibration-fault-diagnosis",
            "pump-fault-diagnosis",
            "reciprocating-fault-diagnosis",
        }

        for kind_name, kind_config in config["kinds"].items():
            assert kind_config["rules_skill"] in valid_rules, (
                f"{kind_name} has invalid rules_skill: {kind_config['rules_skill']}"
            )

    def test_family_values_valid(self):
        config = _load_kind_config()
        valid_families = {"rotating", "pump", "reciprocating"}

        for kind_name, kind_config in config["kinds"].items():
            assert kind_config["family"] in valid_families, (
                f"{kind_name} has invalid family: {kind_config['family']}"
            )

    def test_rotating_kinds_use_vibration_rules(self):
        config = _load_kind_config()
        rotating_kinds = ["centrifugal_compressor", "steam_turbine", "gearbox"]

        for kind in rotating_kinds:
            if kind in config["kinds"]:
                assert config["kinds"][kind]["rules_skill"] == "vibration-fault-diagnosis"
                assert config["kinds"][kind]["family"] == "rotating"

    def test_pump_kinds_use_pump_rules(self):
        config = _load_kind_config()
        pump_kinds = ["centrifugal_pump", "positive_displacement_pump"]

        for kind in pump_kinds:
            if kind in config["kinds"]:
                assert config["kinds"][kind]["rules_skill"] == "pump-fault-diagnosis"
                assert config["kinds"][kind]["family"] == "pump"

    def test_reciprocating_kind_uses_reciprocating_rules(self):
        config = _load_kind_config()
        rc = config["kinds"].get("reciprocating_compressor")
        assert rc is not None
        assert rc["rules_skill"] == "reciprocating-fault-diagnosis"
        assert rc["family"] == "reciprocating"

    def test_default_config_exists(self):
        config = _load_kind_config()
        assert "default" in config
        default = config["default"]
        assert "rules_skill" in default
        assert "family" in default
        assert "focus_codes" in default
        assert "viz_templates" in default

    def test_all_six_kinds_present(self):
        config = _load_kind_config()
        expected_kinds = {
            "centrifugal_compressor",
            "steam_turbine",
            "centrifugal_pump",
            "positive_displacement_pump",
            "reciprocating_compressor",
            "gearbox",
        }
        assert set(config["kinds"].keys()) == expected_kinds


class TestPipelineIntegration:
    """Tasks 7.1/7.2: Pipeline integration from transform to render."""

    def _make_diagnosis(self, root_cause_id: str, severity: str = "high") -> dict:
        label = root_cause_id.replace("_", " ").title()
        return {
            "evidence_chain": [
                {
                    "point": "bearing_temp",
                    "feature": "max_value",
                    "value": 85.2,
                    "threshold": 80.0,
                    "verdict": "exceed",
                    "severity": severity,
                }
            ],
            "rule_matches": [
                {
                    "rule_id": "R001",
                    "root_cause_id": root_cause_id,
                    "label": label,
                    "confidence": "high",
                    "likelihood": "high",
                    "severity": severity,
                    "supporting_evidence_count": 3,
                    "rationale": "Test evidence",
                }
            ],
            "recommendations": [
                {
                    "action": f"Fix {root_cause_id}",
                    "priority": "urgent" if severity in ("high", "critical") else "routine",
                    "rationale": "Test rationale",
                    "timeframe": "24h",
                }
            ],
            "warnings": [],
        }

    def test_basic_single_device_pipeline(self):
        """Basic tier: single device → transform → render."""
        diagnosis = self._make_diagnosis("bearing_wear", "high")

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            input_path = tmpdir / "diagnosis_features.json"
            with open(input_path, "w") as f:
                json.dump(diagnosis, f)

            report = aggregate_diagnosis_reports(
                inputs=[input_path],
                equipment_ids=["EQ001"],
                equipment_names=["压缩机A"],
                capability_tier="basic",
            )

            md = render_diagnosis_markdown(report)

            assert "# 多设备故障诊断报告" in md
            assert "压缩机A" in md
            assert "Bearing Wear" in md
            assert "## 根因排序" in md
            assert "## 维护建议" in md

    def test_pro_multi_device_pipeline(self):
        """Pro tier: multi-device with cross-device correlation → render."""
        diagnosis_1 = self._make_diagnosis("bearing_wear", "high")
        diagnosis_2 = self._make_diagnosis("bearing_wear", "medium")
        diagnosis_3 = self._make_diagnosis("unbalance", "low")

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            paths = []
            for i, d in enumerate([diagnosis_1, diagnosis_2, diagnosis_3], 1):
                p = tmpdir / f"diagnosis_{i}.json"
                with open(p, "w") as f:
                    json.dump(d, f)
                paths.append(p)

            report = aggregate_diagnosis_reports(
                inputs=paths,
                equipment_ids=["EQ001", "EQ002", "EQ003"],
                equipment_names=["压缩机A", "压缩机B", "泵C"],
                capability_tier="pro",
            )

            md = render_diagnosis_markdown(report)

            assert "# 多设备故障诊断报告" in md
            assert "PRO" in md
            assert "压缩机A" in md
            assert "压缩机B" in md
            assert "泵C" in md
            assert "## 跨设备根因关联" in md
            assert "Bearing Wear" in md
            assert "中等关联" in md  # bearing_wear affects 2 devices
            assert "## 影响评估" in md
            assert "## 根因排序" in md

    def test_ultra_fallback_to_pro_pipeline(self):
        """Ultra with model_fallback → renders with fallback warning."""
        diagnosis = self._make_diagnosis("bearing_wear", "high")
        diagnosis["model_fallback"] = True

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            input_path = tmpdir / "diagnosis_features.json"
            with open(input_path, "w") as f:
                json.dump(diagnosis, f)

            report = aggregate_diagnosis_reports(
                inputs=[input_path],
                equipment_ids=["EQ001"],
                equipment_names=["压缩机A"],
                capability_tier="ultra",
            )

            # Simulate fallback: override capability_tier
            report["model_fallback"] = True

            md = render_diagnosis_markdown(report)

            assert "模型回退" in md
            assert "Ultra 模型不可用" in md

    def test_intermediate_files_not_in_report(self):
        """Verify no intermediate file paths leak into the rendered report."""
        diagnosis = self._make_diagnosis("bearing_wear", "high")

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            input_path = tmpdir / "diagnosis_features.json"
            with open(input_path, "w") as f:
                json.dump(diagnosis, f)

            report = aggregate_diagnosis_reports(
                inputs=[input_path],
                equipment_ids=["EQ001"],
                equipment_names=["压缩机A"],
                capability_tier="basic",
            )

            md = render_diagnosis_markdown(report)

            # Intermediate file names should not appear in the report
            assert "fault_context.json" not in md
            assert "diagnosis_features.json" not in md
            assert "diagnosis_report_features.json" not in md
            assert str(tmpdir) not in md

    def test_empty_diagnosis_pipeline(self):
        """Pipeline with no findings still produces valid report."""
        empty_diagnosis = {
            "evidence_chain": [],
            "rule_matches": [],
            "recommendations": [],
            "warnings": [],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            input_path = tmpdir / "diagnosis_features.json"
            with open(input_path, "w") as f:
                json.dump(empty_diagnosis, f)

            report = aggregate_diagnosis_reports(
                inputs=[input_path],
                equipment_ids=["EQ001"],
                equipment_names=["压缩机A"],
                capability_tier="basic",
            )

            md = render_diagnosis_markdown(report)

            assert "# 多设备故障诊断报告" in md
            assert "无根因数据" in md
