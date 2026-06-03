"""Integration smoke test for fault-diagnosis group + 3 sub-agents.

Story S1-8 acceptance (initial) + Story S2-6 expansion (full coverage):

1. Parent group + 3 sub-agent configs are discovered by ``scan_builtin_agents``
2. Each sub-agent SOUL.md uses its own callback_id prefix → no cross-talk
3. Pump / rotating SOULs follow the two-step real-rule runtime contract, while
   reciprocating preserves the staged MVP pipeline contract.
4. ``data_source=demo_fallback`` flows through the MVP pipelines and
   historical_cases are tagged so the SOUL can prefix "演示".
5. The four forbidden structured-summary headings never appear as Markdown
   headings in any of the new SOUL files.
6. Rotating SOUL does not render any chart blocks in the final report;
   reciprocating SOUL skips orbit.
7. Pump / rotating now use the two-step real-rule form flow instead of a focus form.

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
        "fd-pump-device",
        "fd-pump-time",
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
    }
    assert expected.issubset(set(cfg.skills or []))


def test_rotating_subagent_skill_chain_complete():
    """Rotating subagent must mount device-context + rule skill + full ins toolchain."""
    from deerflow.config.agents_config import load_agent_config

    cfg = load_agent_config("fault-diagnosis--rotating")
    assert cfg is not None
    skills = set(cfg.skills or [])
    assert "rotating-device-context" in skills
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
    elif name == "fault-diagnosis--pump":
        assert "sub-device-selector" in soul
        assert "run_pump_rule_diagnosis.py" in soul
        assert "build_pump_report_payload.py" in soul
        assert "pump_rule_result.json" in soul
        assert "pump_rule_cache" in soul
        assert "INS_ACCESS_TOKEN" in soul
        assert "起停机" in soul
    else:
        # Two-stage pull contract
        assert "第一阶段" in soul or "聚合特征拉取" in soul
        assert "第二阶段" in soul or "深度采样" in soul
        # Demo-fallback warning contract (design risk row 9)
        assert "demo_fallback" in soul
        assert "演示" in soul


@pytest.mark.parametrize("name", ["fault-diagnosis--reciprocating"])
def test_subagent_default_selection_documented(name):
    """Pump / reciprocating SOULs must explicitly note the ≤5-device default."""
    soul = _read_soul(name)
    assert "5 台" in soul
    # Explicit deviation from daily 全选 convention must be called out
    assert "日报" in soul and ("全选" in soul or "默认勾选" in soul)


@pytest.mark.parametrize("name", ["fault-diagnosis--reciprocating"])
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


@pytest.mark.parametrize("name", ["fault-diagnosis--reciprocating"])
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


def test_pump_soul_uses_two_step_real_rule_flow():
    """Pump SOUL must use the dedicated device/time callbacks and pump rule scripts."""
    soul = _read_soul("fault-diagnosis--pump")
    blocks = [json.loads(block) for block in re.findall(r"```json\n(.*?)\n```", soul, re.DOTALL)]

    assert len(blocks) >= 2, "pump SOUL should declare device selector + time form"
    assert blocks[0]["component"] == "sub-device-selector"
    assert blocks[0]["callback_id"] == "fd-pump-device"
    assert blocks[0]["props"]["queryParams"]["typeId"] == 4
    assert blocks[0]["props"]["filterDeviceType"] == 4
    assert blocks[0]["callback_timeout_ms"] >= 60_000
    assert blocks[1]["component"] == "form"
    assert blocks[1]["callback_id"] == "fd-pump-time"
    assert blocks[1]["callback_timeout_ms"] >= 60_000
    assert "focus_" not in soul
    assert "device-selector-multi" not in soul
    assert "maxSelect" not in soul
    assert "run_pump_rule_diagnosis.py" in soul
    assert "build_pump_report_payload.py" in soul
    assert "pump_rule_result.json" in soul
    assert "diagnosis_features.json" in soul
    assert "INS_ACCESS_TOKEN" in soul
    assert "不考虑起停机状态" in soul
    command_match = re.search(
        r"python /mnt/skills/custom/pump-fault-diagnosis/scripts/run_pump_rule_diagnosis.py .*?pump_rule_result\.json",
        soul,
        re.DOTALL,
    )
    assert command_match, "pump rule command block missing"
    assert "--start-time" not in command_match.group(0)
    assert "--end-time" not in command_match.group(0)


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


def test_rotating_soul_removes_all_chart_rendering():
    """Rotating SOUL must not render trend / spectrum / orbit charts."""
    soul = _read_soul("fault-diagnosis--rotating")
    assert "render_ui(component=\"echart\"" not in soul
    assert "trend_chart" not in soul
    assert "spectrum_charts[]" not in soul
    assert "orbit_charts[]" not in soul
    assert "最终报告彻底不要图谱" in soul


def test_pump_soul_uses_rule_cache_not_orbit_pipeline():
    """Pump SOUL must use managed rule cache rather than old orbit subprocess calls."""
    soul = _read_soul("fault-diagnosis--pump")
    assert "pump_rule_cache" in soul
    assert "bash /mnt/skills/custom/ins-get-orbit-data" not in soul
    assert "bash /mnt/skills/custom/ins-extract-orbit-centerline-features" not in soul


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


