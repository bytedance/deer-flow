---
name: alere-sia-creator
description: Use this skill to orchestrate the creation of a complete Learning Situation (SIA) for Proyecto Alere, following the 5-node structure.
---

# Alere SIA Orchestration Skill

## Overview
This skill guides the agent through the 5 nodes of an Alere SIA, integrating AI asset generation, competency tagging (SCC), and multi-platform export.

## Workflow

### Node 1: Activation (Desequilibrio Cognitivo)
1. Define a concept or problem that generates curiosity/imbalance.
2. Call `video_veo_tool` to generate a conceptual activation video.

### Node 2: Context & Driving Question
1. Create a simulated scenario that situates the problem.
2. Formulate a "Driving Question" (Pregunta Generadora).

### Node 3: Mobilizing Challenge (Reto)
1. Design the core challenge that demands the mobilization of knowledge.
2. Use `rive_logic_exporter` to define any interactive logic needed for the challenge.

### Node 4: Learning Sequence
1. Generate a sequence of 4 to 5 sessions using active methodologies.
2. For technical parts, use `audio_producer_tool`. For "Detrás del dato", use `suno_song_tool`.

### Node 5: Product & Metacognition
1. Define the final product and create authentic evaluation rubrics.
2. Set up reflective check-ins.

### SCC Tagging & Validation
1. Map all content to the 8 Key Competencies.
2. Call `scc_validator` to ensure compliance. **CRITICAL: 'socioemocional' and 'cultural_artistica' (ConecARTE) must be present.**

### Multi-Platform Export
1. Once validated, call `wiki_exporter` for the Content Wiki.
2. Call `stitch_exporter` for the student frontends (Niños/Adolescentes).
3. Call `teacher_dashboard_generator` for the teacher's portal.

## Mandatory Structure
Final output must follow the schema in `/mnt/user-data/workspace/sia_schema.json` (or `backend/src/models/sia_schema.json`).

## Example Request
"Create an Alere SIA about kinematics in school transportation for 12-year-olds."
