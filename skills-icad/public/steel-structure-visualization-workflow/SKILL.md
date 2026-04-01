---
name: steel-structure-visualization-workflow
description: Use this skill when the user wants DeerFlow to build and visualize a steel-structure model from requirements. It defines the workflow from requirement extraction, to originData JSON authoring, to calling the visualize_steel_structure tool, to presenting VSFX/CDA/properties artifacts.
---

# Steel Structure Visualization Workflow

Follow this workflow when building a steel-structure model:

1. Understand the user's structural requirements.
2. Load the `steel-structure-json-authoring` skill and write a complete `originData` JSON file in `/mnt/user-data/workspace/`.
3. Call `visualize_steel_structure` with the JSON string.
4. The tool writes `.vsfx`, `.cda.json`, and `.properties.json` into `/mnt/user-data/outputs/`.
5. Present those files to the user with `present_files`.

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
