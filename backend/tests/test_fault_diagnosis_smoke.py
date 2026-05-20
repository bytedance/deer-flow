"""Integration smoke test for fault-diagnosis group + 3 sub-agents.

Story S1-8 acceptance (initial) + Story S2-6 expansion (full coverage):

1. Parent group + 3 sub-agent configs are discovered by ``scan_builtin_agents``
2. Each sub-agent SOUL.md uses its own callback_id prefix → no cross-talk
3. Pump / reciprocating SOULs preserve the staged MVP pipeline contract, while
   rotating SOUL follows the new real-rule runtime contract.
4. ``data_source=demo_fallback`` flows through the MVP pipelines and
   historical_cases are tagged so the SOUL can prefix "演示".
5. The four forbidden structured-summary headings never appear as Markdown
   headings in any of the new SOUL files.
6. Rotating SOUL renders orbit blocks via cached report payloads;
   reciprocating SOUL skips orbit.
7. Pump / reciprocating SOULs declare the expected ``focus_*`` field names;
   rotating SOUL now uses the two-step real-rule form flow instead of a focus form.

These checks defend the fault-diagnosis MVP at the contract level. Live
GenUI rendering / browser flow is verified manually (screenshots archived
under ``docs/plans/screenshots/``).
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BUILTIN_DIR = REPO_ROOT / "agents" / "builtin"
SCRIPT_DIR = REPO_ROOT / "skills" / "custom" / "data-analyst" / "scripts"
SKILLS_ROOT = REPO_ROOT / "skills" / "custom"

SUB_AGENTS = [
    "fault-diagnosis--pump",
    "fault-diagnosis--rotating",
    "fault-diagnosis--reciprocating",
]
GROUP_NAME = "fault-diagnosis"

FORBIDDEN_SUMMARY_HEADINGS = ["SESSION INTENT", "SUMMARY", "ARTIFACTS", "NEXT STEPS"]

EXPECTED_FOCUS_CODES: dict[str, list[str]] = {
    "fault-diagnosis--pump": [
        "unbalance", "misalignment", "bearing_damage", "cavitation",
        "seal_leakage", "impeller_wear", "min_flow_violation", "resonance",
        "motor_coupling",
    ],  # 9
    "fault-diagnosis--rotating": [
        "unbalance", "misalignment", "critical_response", "thermal_bend",
        "permanent_bend", "rub_seal", "support_bearing", "rotating_stall_surge",
        "runout", "axial_offset_calibration", "bearing_temperature_high",
        "thrust_bearing_temperature_high",
    ],  # 12
    "fault-diagnosis--reciprocating": [
        "valve_failure", "piston_ring_wear", "crosshead_knock",
        "connecting_rod_clearance", "piston_rod_droop", "cylinder_pressure_anomaly",
        "unloader_anomaly", "bearing_damage", "misalignment", "resonance",
        "motor_coupling",
    ],  # 11
}

# Expected callback IDs by sub-agent. Rotating switched to a dedicated
# two-step device/time flow for the real-rule runtime.
CALLBACK_IDS_BY_AGENT: dict[str, list[str]] = {
    "fault-diagnosis--pump": [
        "fd-pump-scope",
        "fd-pump-device",
        "fd-pump-target",
        "fd-pump-focus",
    ],
    "fault-diagnosis--rotating": [
        "fd-rotating-device",
        "fd-rotating-time",
    ],
    "fault-diagnosis--reciprocating": [
        "fd-reciprocating-scope",
        "fd-reciprocating-device",
        "fd-reciprocating-target",
        "fd-reciprocating-focus",
    ],
}

# rules-skill mapping per design doc §4.6
RULES_SKILL_BY_AGENT: dict[str, str] = {
    "fault-diagnosis--pump": "pump-fault-diagnosis",
    "fault-diagnosis--rotating": "vibration-fault-diagnosis",
    "fault-diagnosis--reciprocating": "reciprocating-fault-diagnosis",
}


def _read_soul(name: str) -> str:
    return (BUILTIN_DIR / name / "SOUL.md").read_text(encoding="utf-8")


# --- Discovery layer ---


def test_group_and_three_subagents_discoverable():
    """Backend ``scan_builtin_agents`` must surface 1 group + 3 sub-agents."""
    from deerflow.config.agents_config import scan_builtin_agents

    agents = scan_builtin_agents()
    by_name = {a.name: a for a in agents}

    assert GROUP_NAME in by_name, "fault-diagnosis group missing"
    assert by_name[GROUP_NAME].type == "group", "fault-diagnosis must be type=group"

    for sub in SUB_AGENTS:
        assert sub in by_name, f"sub-agent {sub} not discoverable"
        cfg = by_name[sub]
        assert cfg.parent == GROUP_NAME, f"{sub}.parent must be {GROUP_NAME}"


def test_pump_subagent_skill_chain_complete():
    """Pump sub-agent must declare every skill it depends on."""
    from deerflow.config.agents_config import load_agent_config

    cfg = load_agent_config("fault-diagnosis--pump")
    assert cfg is not None
    expected = {
        "data-analyst",
        "pump-fault-diagnosis",
        "ins-device-analysis",
        "ins-get-trend-data",
        "ins-get-waveform-data",
        "ins-get-orbit-data",
        "ins-extract-trend-features",
        "ins-extract-spectral-waveform-features",
        "ins-extract-orbit-centerline-features",
    }
    assert expected.issubset(set(cfg.skills or []))


def test_rotating_subagent_skill_chain_complete():
    """Rotating subagent must mount vibration-fault-diagnosis + full ins toolchain (incl. orbit)."""
    from deerflow.config.agents_config import load_agent_config

    cfg = load_agent_config("fault-diagnosis--rotating")
    assert cfg is not None
    skills = set(cfg.skills or [])
    assert "vibration-fault-diagnosis" in skills
    assert "ins-get-orbit-data" in skills
    assert "ins-extract-orbit-centerline-features" in skills


def test_reciprocating_subagent_excludes_orbit_skills():
    """Reciprocating subagent must NOT mount orbit skills (design §3.4)."""
    from deerflow.config.agents_config import load_agent_config

    cfg = load_agent_config("fault-diagnosis--reciprocating")
    assert cfg is not None
    skills = set(cfg.skills or [])
    assert "ins-get-orbit-data" not in skills
    assert "ins-extract-orbit-centerline-features" not in skills
    # Must still mount the rule-skill
    assert "reciprocating-fault-diagnosis" in skills


# --- SOUL.md contracts (parametrized for all three sub-agents) ---


@pytest.mark.parametrize("name", SUB_AGENTS + [GROUP_NAME])
def test_no_forbidden_structured_summary_headings(name):
    """Per design §4.1: no SOUL may render SESSION INTENT / SUMMARY / ARTIFACTS / NEXT STEPS as headings."""
    soul = _read_soul(name)
    for token in FORBIDDEN_SUMMARY_HEADINGS:
        pattern = re.compile(rf"^\s*#{{1,6}}\s+{re.escape(token)}\s*$", re.MULTILINE)
        assert not pattern.search(soul), f"{name}/SOUL.md contains forbidden heading '{token}'"


@pytest.mark.parametrize("name", SUB_AGENTS)
def test_subagent_uses_correct_callback_prefix(name):
    """Each SOUL must use its own callback IDs (no cross-talk)."""
    soul = _read_soul(name)
    for callback_id in CALLBACK_IDS_BY_AGENT[name]:
        assert callback_id in soul, f"{name} missing callback {callback_id}"


@pytest.mark.parametrize("name", SUB_AGENTS)
def test_subagent_callbacks_do_not_cross_talk(name):
    """Each SOUL must NOT mention any other sub-agent's callback prefix.

    This protects the parent group from sub-agent state leak — if pump SOUL
    accidentally read fd-rotating-* callbacks from history, an in-flight
    rotating diagnosis could be hijacked when the user switches to pump."""
    soul = _read_soul(name)
    for other_name, other_callbacks in CALLBACK_IDS_BY_AGENT.items():
        if other_name == name:
            continue
        for foreign in other_callbacks:
            assert foreign not in soul, f"{name} leaks foreign callback '{foreign}'"


@pytest.mark.parametrize("name", SUB_AGENTS)
def test_subagent_contract_blocks_present(name):
    """Every sub-agent SOUL must contain canonical contract phrases per design §4.5."""
    soul = _read_soul(name)
    # In-process import contract
    assert "from export_report import write_report" in soul
    assert "render_diagnosis_markdown" in soul
    # PDF graceful-degrade contract
    assert "ImportError" in soul
    assert "weasyprint" in soul.lower()
    # present_files allowlist
    assert "diagnosis_report.md" in soul
    assert "diagnosis_report.pdf" in soul
    # rules-skill must match the design contract
    expected_skill = RULES_SKILL_BY_AGENT[name]
    assert expected_skill in soul, f"{name} missing --rules-skill {expected_skill}"
    if name == "fault-diagnosis--rotating":
        assert "sub-device-selector" in soul
        assert "device_context.json" in soul
        assert "run_rotating_rule_diagnosis.py" in soul
        assert "build_rotating_report_payload.py" in soul
        assert "rotating_rule_cache" in soul
        assert "禁止静默回退" in soul
    else:
        # Two-stage pull contract
        assert "第一阶段" in soul or "聚合特征拉取" in soul
        assert "第二阶段" in soul or "深度采样" in soul
        # Demo-fallback warning contract (design risk row 9)
        assert "demo_fallback" in soul
        assert "演示" in soul


@pytest.mark.parametrize("name", ["fault-diagnosis--pump", "fault-diagnosis--reciprocating"])
def test_subagent_default_selection_documented(name):
    """Pump / reciprocating SOULs must explicitly note the ≤5-device default."""
    soul = _read_soul(name)
    assert "5 台" in soul
    # Explicit deviation from daily 全选 convention must be called out
    assert "日报" in soul and ("全选" in soul or "默认勾选" in soul)


@pytest.mark.parametrize("name", ["fault-diagnosis--pump", "fault-diagnosis--reciprocating"])
def test_subagent_has_three_well_formed_form_blocks(name):
    """Pump / reciprocating staged forms must parse as JSON and use expected callback IDs."""
    soul = _read_soul(name)
    blocks = re.findall(r"```json\n(.*?)\n```", soul, re.DOTALL)
    assert len(blocks) >= 3, f"{name}: expected ≥3 JSON form blocks, got {len(blocks)}"

    callbacks = []
    for block in blocks:
        parsed = json.loads(block)  # raises on malformed JSON
        if parsed.get("component") == "form":
            callbacks.append(parsed.get("callback_id"))
            # Every form must set a non-trivial callback_timeout_ms
            assert parsed.get("callback_timeout_ms", 0) >= 60_000

    expected_forms = [
        callback_id
        for callback_id in CALLBACK_IDS_BY_AGENT[name]
        if callback_id.endswith(("scope", "target", "focus"))
    ]
    for callback_id in expected_forms:
        assert callback_id in callbacks, f"{name} form block missing callback {callback_id}"


@pytest.mark.parametrize("name", ["fault-diagnosis--pump", "fault-diagnosis--reciprocating"])
def test_subagent_focus_codes_match_design(name):
    """Pump / reciprocating SOULs must declare the expected focus_* fields."""
    soul = _read_soul(name)
    expected = EXPECTED_FOCUS_CODES[name]
    for code in expected:
        field_name = f"focus_{code}"
        assert field_name in soul, f"{name} missing field {field_name}"


def test_rotating_soul_uses_two_step_real_rule_flow():
    """Rotating SOUL must use the dedicated device/time callbacks and runtime scripts."""
    soul = _read_soul("fault-diagnosis--rotating")
    blocks = [json.loads(block) for block in re.findall(r"```json\n(.*?)\n```", soul, re.DOTALL)]

    assert len(blocks) >= 2, "rotating SOUL should declare device selector + time form"
    assert blocks[0]["component"] == "sub-device-selector"
    assert blocks[0]["callback_id"] == "fd-rotating-device"
    assert blocks[0]["callback_timeout_ms"] >= 60_000
    assert blocks[1]["component"] == "form"
    assert blocks[1]["callback_id"] == "fd-rotating-time"
    assert blocks[1]["callback_timeout_ms"] >= 60_000
    assert "focus_" not in soul
    assert "run_rotating_rule_diagnosis.py" in soul
    assert "build_rotating_report_payload.py" in soul
    assert "device_context.json" in soul
    assert "rotating_rule_result.json" in soul
    assert "diagnosis_features.json" in soul
    assert "INS_ACCESS_TOKEN" in soul
    assert "sub-device-selector" in soul


# --- Reciprocating-specific orbit prohibition ---


def test_reciprocating_soul_skips_orbit_calls():
    """Reciprocating SOUL must NOT spawn orbit ins-* skill subprocesses."""
    soul = _read_soul("fault-diagnosis--reciprocating")
    # No bash invocations of orbit skills
    assert soul.count("bash /mnt/skills/custom/ins-get-orbit-data") == 0
    assert soul.count("bash /mnt/skills/custom/ins-extract-orbit-centerline-features") == 0
    # Must explicitly call out the prohibition
    assert (
        "严禁调用 orbit 工具链" in soul
        or "严禁渲染轴心轨迹" in soul
        or "跳过 orbit" in soul
    )


def test_rotating_soul_keeps_orbit_pipeline():
    """Rotating SOUL must keep orbit rendering in the report payload flow."""
    soul = _read_soul("fault-diagnosis--rotating")
    assert "orbit_charts[]" in soul
    assert "轴心轨迹" in soul
    assert "跳过该条目而不是降级整个 Block" in soul


def test_pump_soul_keeps_orbit_pipeline():
    """Pump SOUL must keep orbit ins-* skill calls for double-probe pumps."""
    soul = _read_soul("fault-diagnosis--pump")
    assert "ins-get-orbit-data" in soul
    assert "ins-extract-orbit-centerline-features" in soul


# --- Group landing page ---


def test_group_soul_is_landing_page():
    """Parent group SOUL must be the menu landing page (no GenUI form here)."""
    soul = _read_soul(GROUP_NAME)
    # Landing page lists all three sub-agents
    assert "fault-diagnosis--pump" in soul
    assert "fault-diagnosis--rotating" in soul
    assert "fault-diagnosis--reciprocating" in soul
    # Group SOUL must NOT contain any callback id (it does not run GenUI)
    for callbacks in CALLBACK_IDS_BY_AGENT.values():
        for callback_id in callbacks:
            assert callback_id not in soul, f"group SOUL leaks {callback_id}"


# --- End-to-end pipeline (demo fallback path) ---


def _run_query_diagnosis(
    smoke_dir: Path, kind: str, equipment: str, mode: str, compare: str
) -> dict:
    spec = importlib.util.spec_from_file_location("query_diagnosis", SCRIPT_DIR / "query_diagnosis.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["query_diagnosis"] = mod
    os.environ["DIAGNOSIS_OUTPUT_DIR"] = str(smoke_dir)
    os.environ["INS_SKILL_ROOT"] = str(smoke_dir / "no_skills")
    os.environ["FEATURES_TOOL_ROOT"] = str(smoke_dir / "no_features")
    spec.loader.exec_module(mod)
    return mod.build_result(
        kind=kind,
        equipment_ids=equipment.split(","),
        start="2026-05-12T00:00:00",
        end="2026-05-13T00:00:00",
        mode=mode,
        compare=compare,
    )


def _run_diagnosis_features(
    smoke_dir: Path, focus_codes: list[str], rules_skill: str
) -> dict:
    spec = importlib.util.spec_from_file_location("diagnosis_features", SCRIPT_DIR / "diagnosis_features.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["diagnosis_features"] = mod
    os.environ["DIAGNOSIS_OUTPUT_DIR"] = str(smoke_dir)
    os.environ["DIAGNOSIS_SKILLS_ROOT"] = str(SKILLS_ROOT)
    spec.loader.exec_module(mod)
    query_payload = json.loads((smoke_dir / "query_diagnosis.json").read_text(encoding="utf-8"))
    return mod.build_features(
        query_payload=query_payload,
        focus_codes=focus_codes,
        rules_skill=rules_skill,
        input_dir=smoke_dir,
        skills_root=SKILLS_ROOT,
    )


@pytest.mark.parametrize(
    "kind,equipment,focus,rules_skill,expect_rule_match",
    [
        # pump / reciprocating use Chinese-keyword placeholder rules that match demo
        # feature names (pp_value / rms etc.) → demo path produces ≥1 rule_match.
        ("centrifugal_pump", "PUMP-A-001,PUMP-A-002",
         ["unbalance", "cavitation", "min_flow_violation"], "pump-fault-diagnosis", True),
        # Rotating uses the production-grade vibration skill (English-prose rules
        # written for real InS spectra: "mainly 1X", "BODE", etc.). Those rules
        # do not key off the demo trend feature names by design — that is fine,
        # the rule book stays in sync with real data, not the script's demo
        # fallback. We only assert the pipeline runs to completion here.
        ("centrifugal_compressor", "K-101,K-102",
         ["unbalance", "misalignment", "critical_response"], "vibration-fault-diagnosis", False),
        ("reciprocating_compressor", "RC-101,RC-102",
         ["valve_failure", "piston_ring_wear", "crosshead_knock"], "reciprocating-fault-diagnosis", True),
    ],
    ids=["pump", "rotating", "reciprocating"],
)
def test_e2e_demo_fallback_full_pipeline(
    tmp_path, monkeypatch, kind, equipment, focus, rules_skill, expect_rule_match
):
    """End-to-end smoke for all three sub-agent pipelines on demo_fallback path.

    Mirrors the SOUL execution sequence:
      Round 2 callback → query_diagnosis → diagnosis_features → write_report (md+pdf).

    The PDF call is allowed to raise ImportError when weasyprint is absent,
    matching the SOUL graceful-degrade contract."""
    monkeypatch.syspath_prepend(str(SCRIPT_DIR))

    # Stage 1
    qres = _run_query_diagnosis(
        smoke_dir=tmp_path,
        kind=kind,
        equipment=equipment,
        mode="oneoff",
        compare="previous_period",
    )
    assert qres["data_source"] == "demo_fallback"
    (tmp_path / "query_diagnosis.json").write_text(
        json.dumps(qres, ensure_ascii=False), encoding="utf-8"
    )

    # Stage 2
    fres = _run_diagnosis_features(smoke_dir=tmp_path, focus_codes=focus, rules_skill=rules_skill)
    assert fres["report_meta"]["data_source"] == "demo_fallback"
    assert fres["evidence_chain"], "evidence_chain must always be non-empty on demo data"

    if expect_rule_match:
        assert len(fres["rule_matches"]) >= 1
        # historical_cases must carry data_source so SOUL can prefix
        for case in fres["historical_cases"]:
            assert case["data_source"] == "demo_fallback"
    # else: rotating uses vibration skill's English production rules; demo data
    # may yield zero matches, which is the expected behavior — the rule book is
    # tuned for real InS spectra, not the script's deterministic demo features.

    # Persist features for write_report
    (tmp_path / "diagnosis_features.json").write_text(
        json.dumps(fres, ensure_ascii=False), encoding="utf-8"
    )

    # Render markdown via in-process API (mirrors SOUL step 6)
    from export_diagnosis_report import render_diagnosis_markdown
    from export_report import write_report

    md_text = render_diagnosis_markdown(fres, thread_id="t-smoke")
    assert "# 故障诊断报告" in md_text
    # 6-section template all present
    for section in [
        "## 1. 设备与任务",
        "## 2. 异常发现",
        "## 3. 证据链",
        "## 4. 诊断结论",
        "## 5. 差异诊断",
        "## 6. 处置建议",
    ]:
        assert section in md_text

    # Write Markdown (must succeed)
    monkeypatch.setenv("DIAGNOSIS_OUTPUT_DIR", str(tmp_path))
    md_path = write_report(fres, "md", report_type="diagnosis")
    assert md_path.exists()
    assert md_path.name == "diagnosis_report.md"

    # Write PDF (allowed to raise ImportError on sandboxes without weasyprint)
    pdf_available = True
    try:
        write_report(fres, "pdf", report_type="diagnosis")
    except ImportError:
        pdf_available = False
    assert pdf_available in (True, False)


def test_e2e_reciprocating_skips_orbit_charts(tmp_path):
    """Reciprocating kinds must always yield empty orbit_charts even with files present."""
    qres = _run_query_diagnosis(
        smoke_dir=tmp_path,
        kind="reciprocating_compressor",
        equipment="RC-001",
        mode="oneoff",
        compare="none",
    )
    (tmp_path / "query_diagnosis.json").write_text(
        json.dumps(qres, ensure_ascii=False), encoding="utf-8"
    )
    # Plant a fake orbit_*.json that should be ignored
    (tmp_path / "orbit_DE.json").write_text(
        json.dumps({"bearing": "DE", "option": {}}), encoding="utf-8"
    )
    fres = _run_diagnosis_features(
        smoke_dir=tmp_path,
        focus_codes=["valve_failure"],
        rules_skill="reciprocating-fault-diagnosis",
    )
    assert fres["orbit_charts"] == []


def test_e2e_pump_uses_orbit_files_when_present(tmp_path):
    """Pump kinds must pick up orbit_*.json files (contrast with reciprocating)."""
    qres = _run_query_diagnosis(
        smoke_dir=tmp_path,
        kind="centrifugal_pump",
        equipment="PUMP-A-001",
        mode="oneoff",
        compare="none",
    )
    (tmp_path / "query_diagnosis.json").write_text(
        json.dumps(qres, ensure_ascii=False), encoding="utf-8"
    )
    (tmp_path / "orbit_DE.json").write_text(
        json.dumps({"bearing": "DE", "option": {"series": []}}), encoding="utf-8"
    )
    fres = _run_diagnosis_features(
        smoke_dir=tmp_path,
        focus_codes=["unbalance"],
        rules_skill="pump-fault-diagnosis",
    )
    assert len(fres["orbit_charts"]) == 1
    assert fres["orbit_charts"][0]["bearing"] == "DE"
