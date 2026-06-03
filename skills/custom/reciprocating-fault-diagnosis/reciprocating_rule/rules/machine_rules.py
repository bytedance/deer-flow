"""Machine-level rules — equivalent to machine-rules.yml.

Cross-cylinder diagnosis:
  1. VIB_ABNORMAL: max health across all JSZD channels
  2. CRANK_SHAFT_BREAK: multiple cylinders with impact + JSZD vibration
"""

from __future__ import annotations

from ..config import (
    FAULT_INFO,
    HL_A,
    HL_B,
    HL_B_MINUS,
    HL_C,
    HL_C_MINUS,
    HL_C_PLUS,
    HL_D,
    HL_NAMES,
)
from ..models import DiagnosisItem, Machine


def run_machine_rules(machine: Machine) -> None:
    """Run all machine-level rules."""
    # ① VIB_ABNORMAL: max health across all JSZD channels (machine-level)
    vib_max = HL_A
    for ch in machine.jszd_channels:
        vib_max = max(vib_max, ch.health_all)
    machine.diag_states["VIB_ABNORMAL"] = vib_max

    # ② Crank shaft break (曲轴断裂)
    _eval_crank_shaft_break(machine, vib_max)


def _eval_crank_shaft_break(machine: Machine, vib_max: int) -> None:
    """Crank shaft break diagnosis.

    Equivalent to machine-rules.yml:
      Count cylinders with PISTON_IMPACT_TDC/BDC >= B- OR CYLINDER_SCORING >= B-.

      Level B: impact_count >= 2, each >= B-
      Level C: impact_count >= 2, any >= C-, vib >= B-
      Level D: impact_count >= 2, any >= C-, vib >= C-  (立即停车)
    """
    info = FAULT_INFO["CRANK_SHAFT_BREAK"]

    # Count impact cylinders: max of PISTON_IMPACT + CYLINDER_SCORING
    impact_count_b = 0   # >= B-
    impact_count_c = 0   # >= C-
    has_c_level = False

    for key in machine.keys:
        tdc = key.diag_states.get("PISTON_IMPACT_TDC", HL_A)
        bdc = key.diag_states.get("PISTON_IMPACT_BDC", HL_A)
        scoring = key.diag_states.get("CYLINDER_SCORING", HL_A)
        max_impact = max(tdc, bdc, scoring)

        if max_impact >= HL_C_MINUS:
            impact_count_c += 1
            has_c_level = True
        if max_impact >= HL_B_MINUS:
            impact_count_b += 1

    if impact_count_b < 2:
        return

    # Level D: multiple C-level impacts + vib >= C- (立即停车)
    if impact_count_c >= 2 and vib_max >= HL_C_MINUS:
        machine.diag_states["CRANK_SHAFT_BREAK"] = HL_D
        machine.diag_details.append(DiagnosisItem(
            code="CRANK_SHAFT_BREAK",
            level=HL_NAMES[HL_D],
            level_value=HL_D,
            name=info["name_d"],
            desc=info["desc_d"],
            recommend=info["recommend_d"],
            component=machine.name,
        ).to_dict())
        return

    # Level C: multiple impacts with C-level + vib >= B- (紧急处理)
    if has_c_level and vib_max >= HL_B_MINUS:
        machine.diag_states["CRANK_SHAFT_BREAK"] = HL_C
        machine.diag_details.append(DiagnosisItem(
            code="CRANK_SHAFT_BREAK",
            level=HL_NAMES[HL_C],
            level_value=HL_C,
            name=info["name_c"],
            desc=info["desc_c"],
            recommend=info["recommend_c"],
            component=machine.name,
        ).to_dict())
        return

    # Level B: multiple B-level impacts (密切关注)
    machine.diag_states["CRANK_SHAFT_BREAK"] = HL_B
    machine.diag_details.append(DiagnosisItem(
        code="CRANK_SHAFT_BREAK",
        level=HL_NAMES[HL_B],
        level_value=HL_B,
        name=info["name_b"],
        desc=info["desc_b"],
        recommend=info["recommend_b"],
        component=machine.name,
    ).to_dict())
