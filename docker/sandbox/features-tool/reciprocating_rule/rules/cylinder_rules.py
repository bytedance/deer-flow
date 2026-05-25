"""Cylinder-level rules — equivalent to cylinder-rules.yml + cylinder-piston.yml.

For each Key (keyphasor / cylinder), diagnose:
  1. Piston rod jump (PBY_JUMP)
  2. Cylinder scoring (拉缸)
  3. Piston impact TDC / BDC (撞缸)
  4. Rod looseness / breakage (活塞杆断裂/连杆松动)
"""

from __future__ import annotations

from ..config import (
    FAULT_INFO,
    HL_A,
    HL_B,
    HL_B_MINUS,
    HL_B_PLUS,
    HL_C,
    HL_C_MINUS,
    HL_C_PLUS,
    HL_D,
    HL_NAMES,
    PBY_SZT_SEG_MAP,
)
from ..models import Channel, DiagnosisItem, Key


def run_cylinder_rules(key: Key, machine=None) -> None:
    """Run all cylinder-level rules on a single Key.

    Parameters
    ----------
    key : Key
        The keyphasor / cylinder to diagnose.
    machine : Machine, optional
        If provided, JSZD channels are filtered from machine.jszd_channels
        by key_id. Otherwise falls back to key.channels_by_type("JSZD").
    """
    pby = key.channel_by_type("PBY")
    szt_list = key.channels_by_type("SZT")

    # Get JSZD channels for this key (machine-level, filtered by key_id)
    if machine:
        key_id_str = str(key.id)
        jszd_list = [ch for ch in machine.jszd_channels if ch.key_id == key_id_str]
    else:
        jszd_list = key.channels_by_type("JSZD")

    vib_max_hl = HL_A
    for ch in jszd_list:
        vib_max_hl = max(vib_max_hl, ch.health_all)

    # Store VIB_ABNORMAL in diag_states for use by cylinder rules
    key.diag_states["VIB_ABNORMAL"] = vib_max_hl

    # ① Compute PBY_JUMP: max health across all PBY segments
    if pby:
        pby_jump_hl = HL_A
        for seg_name, seg_hl in pby.health_segs.items():
            pby_jump_hl = max(pby_jump_hl, seg_hl)
        # Also consider main health
        pby_jump_hl = max(pby_jump_hl, pby.health_all)
        key.diag_states["PBY_JUMP"] = pby_jump_hl
    else:
        key.diag_states["PBY_JUMP"] = HL_A

    # ② Cylinder scoring (拉缸)
    if pby and pby_jump_hl >= HL_B:
        _eval_cylinder_scoring(key, pby, vib_max_hl)

    # ③ Piston impact (撞缸)
    for szt in szt_list:
        _eval_piston_impact(key, szt)

    # ④ Rod looseness
    if pby and szt_list and key.diag_states.get("PBY_JUMP", HL_A) >= HL_B:
        _eval_rod_looseness(key, pby, szt_list, vib_max_hl)


def _eval_cylinder_scoring(key: Key, pby: Channel, vib_max_hl: int) -> None:
    """Cylinder scoring diagnosis.

    Equivalent to cylinder-piston.yml CYLINDER_SCORING:
      - Initial (B+): PBY jump >= B AND machine vibration == A
      - Developed (C): PBY jump > B (no vibration constraint)
    """
    pby_jump = key.diag_states.get("PBY_JUMP", HL_A)
    info = FAULT_INFO["CYLINDER_SCORING"]

    # Collect abnormal PBY segments
    abnormal_segs = [
        seg for seg, hl in pby.health_segs.items() if hl >= HL_B
    ]
    props = ",".join(abnormal_segs) if abnormal_segs else "ALL"

    if pby_jump > HL_B:
        # Developed stage (C): PBY jump > B, no vibration constraint
        key.diag_states["CYLINDER_SCORING"] = HL_C
        key.diag_details.append(DiagnosisItem(
            code="CYLINDER_SCORING",
            level=HL_NAMES[HL_C],
            level_value=HL_C,
            name=info["name_dev"],
            desc=info["desc_dev"],
            recommend=info["recommend_dev"],
            component=key.name,
        ).to_dict())

    elif pby_jump >= HL_B and vib_max_hl == HL_A:
        # Initial stage (B+): PBY jump >= B AND vibration normal
        key.diag_states["CYLINDER_SCORING"] = HL_B_PLUS
        key.diag_details.append(DiagnosisItem(
            code="CYLINDER_SCORING",
            level=HL_NAMES[HL_B_PLUS],
            level_value=HL_B_PLUS,
            name=info["name_init"],
            desc=info["desc_init"],
            recommend=info["recommend_init"],
            component=key.name,
        ).to_dict())


def _eval_piston_impact(key: Key, szt: Channel) -> None:
    """Piston impact diagnosis (TDC and BDC).

    Equivalent to cylinder-piston.yml PISTON_IMPACT_TDC / PISTON_IMPACT_BDC:
      TDC (盖侧): SZT A0/A35 health
        max(A0,A35) >= C → C+ "撞缸（盖侧/严重）"
        max(A0,A35) >= B → B+ "撞缸（盖侧/轻微）"
      BDC (轴侧): SZT A17/A18 health
        max(A17,A18) >= C → C+ "撞缸（轴侧/严重）"
        max(A17,A18) >= B → B+ "撞缸（轴侧/轻微）"
    """
    info_tdc = FAULT_INFO["PISTON_IMPACT_TDC"]
    info_bdc = FAULT_INFO["PISTON_IMPACT_BDC"]

    # TDC: A0 and A35
    hl_a0 = szt.health_segs.get("A0", HL_A)
    hl_a35 = szt.health_segs.get("A35", HL_A)
    tdc_max = max(hl_a0, hl_a35)

    if tdc_max >= HL_C:
        key.diag_states["PISTON_IMPACT_TDC"] = HL_C_PLUS
        # Set CY-IMPACT for machine-level cross-cylinder diagnosis
        key.diag_states["CY-IMPACT"] = max(
            key.diag_states.get("CY-IMPACT", HL_A), HL_C_PLUS
        )
        key.diag_details.append(DiagnosisItem(
            code="PISTON_IMPACT_TDC",
            level=HL_NAMES[HL_C_PLUS],
            level_value=HL_C_PLUS,
            name=info_tdc["name_major"],
            desc=info_tdc["desc"],
            recommend=info_tdc["recommend"],
            component=key.name,
        ).to_dict())
    elif tdc_max >= HL_B:
        key.diag_states["PISTON_IMPACT_TDC"] = HL_B_PLUS
        key.diag_states["CY-IMPACT"] = max(
            key.diag_states.get("CY-IMPACT", HL_A), HL_B_PLUS
        )
        key.diag_details.append(DiagnosisItem(
            code="PISTON_IMPACT_TDC",
            level=HL_NAMES[HL_B_PLUS],
            level_value=HL_B_PLUS,
            name=info_tdc["name_minor"],
            desc=info_tdc["desc"],
            recommend=info_tdc["recommend"],
            component=key.name,
        ).to_dict())

    # BDC: A17 and A18
    hl_a17 = szt.health_segs.get("A17", HL_A)
    hl_a18 = szt.health_segs.get("A18", HL_A)
    bdc_max = max(hl_a17, hl_a18)

    if bdc_max >= HL_C:
        key.diag_states["PISTON_IMPACT_BDC"] = HL_C_PLUS
        key.diag_states["CY-IMPACT"] = max(
            key.diag_states.get("CY-IMPACT", HL_A), HL_C_PLUS
        )
        key.diag_details.append(DiagnosisItem(
            code="PISTON_IMPACT_BDC",
            level=HL_NAMES[HL_C_PLUS],
            level_value=HL_C_PLUS,
            name=info_bdc["name_major"],
            desc=info_bdc["desc"],
            recommend=info_bdc["recommend"],
            component=key.name,
        ).to_dict())
    elif bdc_max >= HL_B:
        key.diag_states["PISTON_IMPACT_BDC"] = HL_B_PLUS
        key.diag_states["CY-IMPACT"] = max(
            key.diag_states.get("CY-IMPACT", HL_A), HL_B_PLUS
        )
        key.diag_details.append(DiagnosisItem(
            code="PISTON_IMPACT_BDC",
            level=HL_NAMES[HL_B_PLUS],
            level_value=HL_B_PLUS,
            name=info_bdc["name_minor"],
            desc=info_bdc["desc"],
            recommend=info_bdc["recommend"],
            component=key.name,
        ).to_dict())


def _eval_rod_looseness(
    key: Key,
    pby: Channel,
    szt_list: list[Channel],
    vib_max_hl: int,
) -> None:
    """Rod looseness / breakage diagnosis.

    Equivalent to cylinder-piston.yml ROD_LOOSENESS:
      Check PBY-SZT segment correspondence:
        PBY A0 → SZT A1,A2,A3,A4
        PBY A1 → SZT A4,A5,A6,A7,A8
        ...
      Condition 1 (C+): PBY seg >= B AND corresponding SZT seg >= B AND vib == A
      Condition 2 (D): Above + vib >= C
    """
    info = FAULT_INFO["ROD_LOOSENESS"]

    # Collect PBY abnormal segments
    pby_abnormal: dict[str, int] = {}
    for seg_name, seg_hl in pby.health_segs.items():
        if seg_hl >= HL_B:
            pby_abnormal[seg_name] = seg_hl

    if not pby_abnormal:
        # Also check main health
        if pby.health_all >= HL_B:
            pby_abnormal["ALL"] = pby.health_all
        else:
            return

    # Check SZT correspondence
    matched = False
    for pby_seg, szt_segs in PBY_SZT_SEG_MAP.items():
        if pby_seg not in pby_abnormal:
            continue
        # Check if any corresponding SZT segment is also abnormal
        for szt in szt_list:
            for szt_seg in szt_segs:
                szt_hl = szt.health_segs.get(szt_seg, HL_A)
                if szt_hl >= HL_B:
                    matched = True
                    break
            if matched:
                break
        if matched:
            break

    if not matched:
        return

    # Condition 1: vib normal (A) → C+ warning
    # Condition 2: vib >= C → D severe
    if vib_max_hl >= HL_C:
        key.diag_states["ROD_LOOSENESS"] = HL_D
        key.diag_details.append(DiagnosisItem(
            code="ROD_LOOSENESS",
            level=HL_NAMES[HL_D],
            level_value=HL_D,
            name=info["name_severe"],
            desc=info["desc_severe"],
            recommend=info["recommend_severe"],
            component=key.name,
        ).to_dict())
    else:
        key.diag_states["ROD_LOOSENESS"] = HL_C_PLUS
        key.diag_details.append(DiagnosisItem(
            code="ROD_LOOSENESS",
            level=HL_NAMES[HL_C_PLUS],
            level_value=HL_C_PLUS,
            name=info["name_warn"],
            desc=info["desc_warn"],
            recommend=info["recommend_warn"],
            component=key.name,
        ).to_dict())
