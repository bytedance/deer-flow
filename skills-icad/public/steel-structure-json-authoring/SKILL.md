---
name: steel-structure-json-authoring
description: Use this skill when the user wants a steel-structure model to be authored as iCAD originData JSON, especially for portal frames, factory buildings, steel columns, beams, bracing, purlins, panels, and openings. This skill teaches the agent to follow docs/json schema and rules before calling the visualize tool.
---

# Steel Structure JSON Authoring

Write complete `originData` JSON for iCAD steel-structure modeling.

## Source Rules

Read these bundled reference files before writing the JSON:

- `/mnt/skills/public/steel-structure-json-authoring/references/prompt_json_schema.md`
- `/mnt/skills/public/steel-structure-json-authoring/references/prompt_json_rules.md`

These files are packaged with the skill so they are available inside the deployed sandbox image.

## Required Behavior

- Use the schema's original English keys in the JSON.
- Do not translate, rename, or reshape schema fields.
- For new modeling, output the full top-level structure with required fields.
- Never emit `N/A`, `null`, or placeholder guesses for missing values.
- Keep all lengths, elevations, and coordinates in meters unless the rule explicitly requires section strings in millimeters.
- Section references inside members must point to section-table IDs, never inline section strings.

## Authoring Workflow

1. Extract building requirements from the user request.
2. If any safety-critical load meaning is ambiguous, ask for clarification before modeling.
3. Write the complete JSON file in `/mnt/user-data/workspace/`.
4. Re-check the JSON against the schema/rules docs.
5. Pass the JSON string to the steel-structure visualize tool.

## Output Discipline

- User-facing prose should describe the model naturally.
- The JSON file itself must keep the original schema key names.
