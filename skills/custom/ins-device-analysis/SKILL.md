---
name: ins-device-analysis
description: Use this skill when the user wants the raw child-device tree for an InS machine ID. This wraps `features-tool/tools/device_analysis.py`, which now only fetches interface data and does not perform model-based inference.
---

# InS Device Analysis

Use this skill to fetch the raw child-device tree for an InS machine ID.

## When to Use This Skill

Use this skill when the user:

- Knows a device or machine ID and wants its child-device tree
- Wants the raw normalized child-device tree before downstream diagnosis
- Wants to inspect the structure returned directly by the InS API
- Mentions `device_analysis.py`

## Preconditions

- The workspace contains `features-tool/`
- The target device ID is known
- Required InS env vars are already available to the tool runtime

## Execution Rules

- Pass the device ID as the only argument
- Return the JSON output directly unless the user asks for summarization
- Do not claim the tool inferred device type, process type, or structure
- If the user wants higher-level interpretation, do that in a later step based on the returned tree

## Command

```bash
bash /mnt/skills/custom/ins-device-analysis/scripts/run.sh 180906045526625
```

## Output

The tool returns JSON with:

- `device_id`
- `child_device_list`

## Notes

- This skill is useful as a preprocessing step before vibration diagnosis workflows
- This skill no longer calls an LLM internally
