"""Pin both upload-context consumers to the same JSON wire contract."""

import json
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from deerflow.utils.upload_context import UPLOAD_CONTEXT_KEY, UPLOAD_CONTEXT_VERSION, upload_context_text

CONTRACT = json.loads((Path(__file__).resolve().parents[2] / "contracts" / "upload_context_contract.json").read_text(encoding="utf-8"))


def test_upload_context_contract_key_and_version():
    assert UPLOAD_CONTEXT_KEY == CONTRACT["metadata_key"]
    assert UPLOAD_CONTEXT_VERSION == CONTRACT["supported_version"]


@pytest.mark.parametrize("case", CONTRACT["cases"], ids=lambda case: case["name"])
def test_upload_context_validity_matches_shared_contract(case):
    kwargs = {CONTRACT["metadata_key"]: case["metadata"]} if "metadata" in case else {}
    cls = HumanMessage if case["message_type"] == "human" else AIMessage
    message = cls(content="User text", additional_kwargs=kwargs)
    expected = case["metadata"]["text"] if case["valid"] else None
    assert upload_context_text(message) == expected
