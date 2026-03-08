"""Rive Logic Exporter tool for Alere's interactive components."""

import json
import os
from typing import Dict, Any
from langchain.tools import tool

@tool("rive_logic_exporter", parse_docstring=True)
def rive_logic_exporter(
    node_id: str,
    logic_data: str,
    output_path: str
) -> str:
    """Exports node logic to a format compatible with Rive components designed in Figma.
    Allows students to manipulate vectors (forces) or flowcharts dynamically.

    Args:
        node_id: The ID of the Alere SIA node the logic belongs to.
        logic_data: A JSON string containing state machines, triggers, and vector parameters.
        output_path: The absolute path for the generated Rive logic file (.json).
    """
    try:
        data = json.loads(logic_data)

        # Structure for Rive consumption (e.g., state machines, inputs)
        rive_json = {
            "node_id": node_id,
            "version": "1.0",
            "type": "Alere_Interactive_Component",
            "rive_parameters": data,
            "figma_reference": f"https://figma.com/alere/components/{node_id}"
        }

        # Check output directory exists
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        # Export the formatted JSON
        with open(output_path, "w") as f:
            json.dump(rive_json, f, indent=4)

        return f"Interactive logic successfully exported for Rive component at {output_path}."

    except json.JSONDecodeError:
        return f"Error: Invalid JSON logic data provided for node {node_id}."
    except Exception as e:
        return f"Error exporting Rive logic: {str(e)}"
