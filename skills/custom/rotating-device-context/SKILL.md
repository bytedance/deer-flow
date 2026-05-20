---
name: rotating-device-context
description: Use this skill when the rotating diagnosis flow needs the current Agent to infer a standard `device_context.json` from raw InS device tree data, using the same model context rather than a separate Python-side LLM call.
metadata:
  emoji: "🧭"
---

# Rotating Device Context

Use this skill in rotating diagnosis Step 2 when you need to build `/mnt/user-data/outputs/device_context.json`.

## Goal

Turn:

- machine metadata from `machine_service.get_machine_info_by_ids`
- raw tree from `python /opt/features-tool/tools/device_analysis.py "{macId}" --output /mnt/user-data/outputs/device_tree_raw.json`

into a standard JSON artifact:

- `/mnt/user-data/outputs/device_context.json`

The current Agent must do the reasoning itself. Do not call a separate Python-side LLM for this step.

## Required Output

Write exactly one valid JSON object with these top-level fields:

- `device_id`
- `child_device_summary`
- `device_type`
- `process_type`
- `device_structure`
- `child_device_list`
- `target_info`

`device_type`, `process_type`, and `device_structure` must each contain:

- `value`
- `confidence`
- `reason`

## Rules

- Preserve all valid measurement points in `child_device_list`; do not silently drop points.
- When `type_num=82` points are not mounted under the correct `80/70` nodes, infer the most likely placement from names and structure.
- Prefer placing thrust-bearing related points on the drive-end / coupling-end side when the evidence supports it.
- If a `type_num=82` point name contains axis-vibration or speed semantics that should be ignored for this artifact, omit that point explicitly and keep the rest of the tree intact.
- If the selected `componentId` cannot be resolved, set `target_info.target_kind` to `"unknown"` and explain why in the surrounding agent response.

## Target Info

`target_info` must at least contain:

- `target_kind`
- `probe_ids`
- `waveform_probe_ids`
- `bearing_ids`
- `owner_device_id`
- `target_device_type`

Allowed `target_kind` values:

- `probe`
- `bearing`
- `rotor_device`
- `unknown`

## Template

Before writing the file, read [references/device_context_template.json](references/device_context_template.json) and follow its shape exactly.
