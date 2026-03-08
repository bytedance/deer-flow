import json
import pytest
from src.tools.alere.scc_validator import scc_validator

def test_scc_validator_success():
    sia = {
        "metadata": {"title": "Test", "target_age": "Niños", "global_theme": "Physics"},
        "competencies_mapping": {
            "comunicativa": "Mapped",
            "matematica_cientifica": "Mapped",
            "digital": "Mapped",
            "innovacion": "Mapped",
            "ciudadana": "Mapped",
            "socioemocional": "Mapped",
            "cultural_artistica": "Mapped",
            "corporal": "Mapped"
        }
    }
    result = scc_validator.invoke({"sia_content": json.dumps(sia)})
    assert "SUCCESS" in result

def test_scc_validator_fail_critical():
    sia = {
        "metadata": {"title": "Test", "target_age": "Niños", "global_theme": "Physics"},
        "competencies_mapping": {
            "comunicativa": "Mapped",
            "socioemocional": "" # Empty mandatory
        }
    }
    result = scc_validator.invoke({"sia_content": json.dumps(sia)})
    assert "FAILED" in result
    assert "socioemocional" in result
