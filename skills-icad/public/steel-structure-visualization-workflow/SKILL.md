---
name: steel-structure-visualization-workflow
description: Use this skill when the user wants DeerFlow to build and visualize a steel-structure model from requirements. It defines the workflow from requirement extraction, to originData JSON authoring, to calling the visualize_steel_structure tool, to presenting VSFX/CDA/properties artifacts.
---

# Steel Structure Visualization Workflow

Follow this workflow when building a steel-structure model:

1. Understand and complete the user's requirements.
2. Validate the completed requirements for modeling legality.
3. Load the `steel-structure-json-authoring` skill and write a complete `originData` JSON file in `/mnt/user-data/workspace/`.
4. Call `visualize_steel_structure` with the JSON string.
5. The tool writes `.vsfx`, `.cda.json`, and `.properties.json` into `/mnt/user-data/outputs/`.
6. Present those files to the user with `present_files`.

## Requirement Understanding

Treat requirement understanding as two explicit stages before JSON authoring.

### Stage 1: Understand and complete the user's requirements

- Read the bundled reference `/mnt/skills/public/steel-structure-visualization-workflow/references/column-spacing-inference.md` before inferring column spacing.
- First summarize the user's stated constraints and complete any missing but inferable requirements.
- If the user does not specify column spacing or spans, infer them before authoring the JSON.
- For column spacing inference, follow the bundled symmetric distribution guidance, prioritizing integers or 0.5m increments.
- For span inference, default to a left-right symmetric layout along the building width and prefer integer spans whenever practical.
- When the user requests multi-ridge roofs, use an even span count of `4` or more, keep the spans as equal as possible, and allow decimal spans when needed.
- No single span may exceed `36m`; if it would, increase the span count and recalculate.
- If some values still cannot be inferred reliably, keep the confirmed requirements and avoid inventing unsupported details.

### Stage 2: Validate the completed requirements for modeling legality

- Check openings against the eave height before writing JSON.
- Door tops and window tops must be at least `0.3m` below the eave height.
- If a window is above a door, keep at least `0.2m` between the window bottom and the door top.
- Automatically adjust door/window heights or window positions when the correction is reliable.
- If a compliant correction cannot be inferred with confidence, preserve only the values that can be determined confidently and leave the uncertain field unset rather than guessing.

## Tool Usage

Use the visualize tool only after the JSON is complete.

- `origin_data_json`: the full JSON string
- `model_name`: a readable model name
- `artifact_prefix`: optional filename prefix for outputs

## Artifact Expectations

The visualize tool writes:

- one `.vsfx`
- one `.cda.json`
- one `.properties.json`

Do not separately archive the original `originData` unless the user explicitly asks for it.

## Failure Handling

- If the tool returns `apfIssues`, inspect them before claiming success.
- If the issues indicate recoverable JSON mistakes, load the APF repair skill and revise the JSON.
