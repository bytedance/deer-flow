"""Multi-platform Exporters for Alere: Wiki, Google Stitch, and Teacher Dashboard."""

import json
import os
from typing import Dict, Any
from langchain.tools import tool

@tool("wiki_exporter", parse_docstring=True)
def wiki_exporter(
    sia_json: str,
    output_path: str
) -> str:
    """Exports the SIA content to a Markdown format for the Alere Content Wiki (Bridge Box).
    Acts as a bilingual technical repository and knowledge query bridge.

    Args:
        sia_json: The complete SIA JSON data.
        output_path: The absolute path for the generated .md file.
    """
    try:
        data = json.loads(sia_json)
        metadata = data.get("metadata", {})
        nodes = data.get("nodes", {})

        md_content = f"# SIA: {metadata.get('title', 'Untitled')}\n\n"
        md_content += f"**Target:** {metadata.get('target_age')}\n"
        md_content += f"**Theme:** {metadata.get('global_theme')}\n\n"

        md_content += "## 1. Activation (Desequilibrio Cognitivo)\n"
        md_content += f"{nodes.get('node_1_activation', {}).get('cognitive_imbalance', 'N/A')}\n\n"

        md_content += "## 2. Context & Driving Question\n"
        node2 = nodes.get('node_2_context', {})
        md_content += f"**Scenario:** {node2.get('scenario', 'N/A')}\n"
        md_content += f"**Question:** {node2.get('driving_question', 'N/A')}\n\n"

        md_content += "## 3. Mobilizing Challenge\n"
        md_content += f"{nodes.get('node_3_challenge', {}).get('challenge_description', 'N/A')}\n\n"

        md_content += "## 4. Learning Sequence\n"
        for i, session in enumerate(nodes.get('node_4_sequence', []), 1):
            md_content += f"### Session {i}: {session.get('session_title')}\n"
            md_content += f"- **Methodology:** {session.get('methodology')}\n"
            md_content += f"- **Activities:** {', '.join(session.get('activities', []))}\n\n"

        md_content += "## 5. Final Product & Metacognition\n"
        node5 = nodes.get('node_5_product', {})
        md_content += f"**Product:** {node5.get('final_product')}\n"
        md_content += f"**Check-ins:** {', '.join(node5.get('metacognition_checkins', []))}\n"

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w") as f:
            f.write(md_content)

        return f"SIA Wiki documentation successfully exported to {output_path}."
    except Exception as e:
        return f"Error exporting to Wiki: {str(e)}"

@tool("stitch_exporter", parse_docstring=True)
def stitch_exporter(
    sia_json: str,
    output_path: str
) -> str:
    """Exports the SIA content to a structured JSON for Google Stitch frontend (Niños/Adolescentes).

    Args:
        sia_json: The complete SIA JSON data.
        output_path: The absolute path for the generated .json file.
    """
    try:
        data = json.loads(sia_json)
        # Add frontend-specific metadata for Stitch
        data["stitch_config"] = {
            "layout": "dynamic_scrollytelling" if data['metadata']['target_age'] == "Adolescentes" else "interactive_blocks",
            "theme": "alere_modern"
        }

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(data, f, indent=4)

        return f"SIA JSON for Google Stitch successfully exported to {output_path}."
    except Exception as e:
        return f"Error exporting to Stitch: {str(e)}"

@tool("teacher_dashboard_generator", parse_docstring=True)
def teacher_dashboard_generator(
    sia_json: str,
    output_path: str
) -> str:
    """Generates Lesson Plans and Pedagogical Labs for the Teacher Dashboard.

    Args:
        sia_json: The complete SIA JSON data.
        output_path: The absolute path for the teacher guide (.md).
    """
    try:
        data = json.loads(sia_json)
        metadata = data.get("metadata", {})

        guide = f"# Teacher Guide: {metadata.get('title')}\n\n"
        guide += "## Pedagogical Objectives\n"
        guide += "This SIA focuses on mobilizing knowledge through active methodologies.\n\n"

        guide += "## Competency Mapping (SCC)\n"
        mapping = data.get("competencies_mapping", {})
        for k, v in mapping.items():
            guide += f"- **{k.replace('_', ' ').title()}:** {v}\n"

        guide += "\n## Laboratory Instructions\n"
        guide += "1. Prepare interactive Rive components.\n"
        guide += "2. Launch Activation Video.\n"
        guide += "3. Guide students through the mobilization challenge.\n"

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w") as f:
            f.write(guide)

        return f"Teacher Dashboard content successfully generated at {output_path}."
    except Exception as e:
        return f"Error generating Teacher Dashboard content: {str(e)}"
