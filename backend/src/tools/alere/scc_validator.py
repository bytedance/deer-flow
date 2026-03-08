"""SCC (Competency) Tagging System and Validator for Alere Projects."""

import json
from typing import Dict, List, Optional
from langchain.tools import tool

COMPETENCIES = [
    "comunicativa",
    "matematica_cientifica",
    "digital",
    "innovacion",
    "ciudadana",
    "socioemocional",
    "cultural_artistica",
    "corporal"
]

MANDATORY_COMPETENCIES = [
    "socioemocional",
    "cultural_artistica" # Corresponds to ConecARTE
]

@tool("scc_validator", parse_docstring=True)
def scc_validator(sia_content: str) -> str:
    """Validates that all 8 Key Competencies of Alere are mapped in the SIA content.
    Specifically checks for 'socioemocional' and 'cultural_artistica' (ConecARTE).

    Args:
        sia_content: The JSON string of the SIA to validate.
    """
    try:
        data = json.loads(sia_content)
        mapping = data.get("competencies_mapping", {})

        missing = []
        for comp in COMPETENCIES:
            if comp not in mapping or not mapping[comp]:
                missing.append(comp)

        if missing:
            critical_missing = [m for m in missing if m in MANDATORY_COMPETENCIES]
            if critical_missing:
                return f"Validation FAILED. Missing critical competencies: {', '.join(critical_missing)}. Full missing list: {', '.join(missing)}"
            return f"Validation WARNING. Missing competencies: {', '.join(missing)}. Please ensure all are mapped for complete SCC compliance."

        return "Validation SUCCESS. All 8 competencies are correctly mapped."

    except json.JSONDecodeError:
        return "Error: Invalid JSON content provided to scc_validator."
    except Exception as e:
        return f"Error during validation: {str(e)}"
