"""Channel-level rules — equivalent to ch-rules.yml + ch-main-alarm.yml + ch-seg-alarm.yml + ch-seg-config.yml.

Each channel is evaluated independently for:
  1. Start/stop gate (skip if stopped or signal error)
  2. Main feature value alarm (4-level threshold with 0.38 coefficient)
  3. Segment alarm (per-angle-domain threshold)
"""

from __future__ import annotations

from ..config import (
    AL_ALERT,
    AL_H,
    AL_HH,
    AL_NORMAL,
    HL_A,
    HL_B,
    HL_B_MINUS,
    HL_C,
    HL_C_MINUS,
    HL_D,
    SEG_ALARM_ENABLE,
    SS_NORMAL,
)
from ..models import Channel


def run_ch_rules(ch: Channel) -> None:
    """Run all channel-level rules on a single Channel."""
    # Gate: skip if alarm is disabled
    if not ch.is_alarm:
        return

    # Gate: skip if signal error
    if ch.signal_state != 0:
        ch.health_all = HL_A
        return

    # ① Main feature value alarm
    if ch.alarm_model and ch.main_value:
        _eval_main_alarm(ch)

    # ② Segment alarm
    if ch.seg_values and ch.seg_thresholds:
        _eval_seg_alarm(ch)


def _eval_main_alarm(ch: Channel) -> None:
    """Evaluate main feature value against 4-level thresholds.

    Equivalent to ch-main-alarm.yml:
      value >= hh → D (40)
      value >= h  → C (30)
      value >= h × 0.38 → B (20)
      else → A (10)

    Same logic for low limits (ll, l, l × 0.38).
    Takes the more severe of high and low results.
    """
    value = ch.main_value
    hh = ch.thresholds.get("hh", 0.0)
    h = ch.thresholds.get("h", 0.0)
    ll = ch.thresholds.get("ll", 0.0)
    l = ch.thresholds.get("l", 0.0)

    health_high = HL_A
    alarm_high = AL_NORMAL

    # High-limit judgment
    if hh > 0 and value >= hh:
        health_high = HL_D
        alarm_high = AL_HH
    elif h > 0 and value >= h:
        health_high = HL_C
        alarm_high = AL_H
    elif h > 0 and value >= h * 0.38:
        health_high = HL_B
        alarm_high = AL_ALERT

    # Low-limit judgment
    health_low = HL_A
    alarm_low = AL_NORMAL

    if ll < 0 and value <= ll:
        health_low = HL_D
        alarm_low = AL_HH
    elif l < 0 and value <= l:
        health_low = HL_C
        alarm_low = AL_H
    elif l < 0 and value <= l * 0.38:
        health_low = HL_B
        alarm_low = AL_ALERT

    # Take the more severe
    if health_high >= health_low:
        ch.health_all = max(ch.health_all, health_high)
        ch.alarm_level = alarm_high
    else:
        ch.health_all = max(ch.health_all, health_low)
        ch.alarm_level = alarm_low


def _eval_seg_alarm(ch: Channel) -> None:
    """Evaluate segment (angle-domain) alarm.

    Equivalent to ch-seg-alarm.yml + ch-seg-config.yml:
      - Only evaluate enabled segments (per position_type)
      - For each enabled segment i:
          seg_values[i] >= hh[i] → D
          seg_values[i] >= h[i]  → C
          seg_values[i] >= h[i] × 0.38 → B
          else → A
      - Combined health = max of all segment healths + main health
    """
    enabled_segs = SEG_ALARM_ENABLE.get(ch.position_type, [])
    if not enabled_segs:
        return

    hh_arr = ch.seg_thresholds.get("hh") or []
    h_arr = ch.seg_thresholds.get("h") or []

    if not hh_arr and not h_arr:
        return

    for seg_name in enabled_segs:
        # Parse segment index from name (e.g., "A0" → 0, "A17" → 17)
        try:
            seg_idx = int(seg_name[1:])
        except (ValueError, IndexError):
            continue

        if seg_idx >= len(ch.seg_values):
            continue

        seg_value = ch.seg_values[seg_idx]

        hh_val = hh_arr[seg_idx] if seg_idx < len(hh_arr) else 0.0
        h_val = h_arr[seg_idx] if seg_idx < len(h_arr) else 0.0

        seg_health = HL_A

        if hh_val > 0 and seg_value >= hh_val:
            seg_health = HL_D
        elif h_val > 0 and seg_value >= h_val:
            seg_health = HL_C
        elif h_val > 0 and seg_value >= h_val * 0.38:
            seg_health = HL_B

        if seg_health > HL_A:
            ch.health_segs[seg_name] = seg_health
            ch.health_all = max(ch.health_all, seg_health)
