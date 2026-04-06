---
name: steel-structure-apf-repair
description: Use this skill when the steel-structure visualize tool returns APF issues or model-build validation errors. It helps the agent map APF issue codes and hints back to originData subsystems, repair the JSON, and retry visualization.
---

# Steel Structure APF Repair

When visualization returns `apfIssues` or `MODEL_BUILD_INPUT_INVALID`, repair the JSON instead of guessing.

## Repair Loop

1. Read each APF issue's `code`, `message`, `context`, `hint`, `subsystem`, and `recoverable`.
2. Map the issue to the affected JSON subsystem.
3. Edit the JSON in `/mnt/user-data/workspace/`.
4. Re-run the visualize tool.

## Common Repair Patterns

- `axis_missing` / `z_axis_missing`: check main axes or auxiliary axes.
- `section_parse_error`: check section-table IDs and section-string formats.
- `beam_id_invalid` / `column_label_invalid`: check location key syntax.
- `roof_height_fallback`: check roof slope and roof/eave geometry.
- `opening_*`: check opening axes, elevations, and section chains.

## Stop And Clarify

Ask the user before retrying if:

- the load definition is safety-critical and ambiguous
- the request is missing essential geometry
- two competing interpretations would produce materially different structures
