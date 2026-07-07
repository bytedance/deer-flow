from deerflow.agents.human_input import read_human_input_response


def _text_response(value: str):
    return {
        "version": 1,
        "kind": "human_input_response",
        "source": "ask_clarification",
        "request_id": "clarification:call-abc",
        "response_kind": "text",
        "value": value,
    }


def test_read_human_input_response_requires_non_empty_value():
    assert read_human_input_response({"human_input_response": _text_response("")}) is None
    assert read_human_input_response({"human_input_response": _text_response("   ")}) is None


def test_read_human_input_response_preserves_non_empty_value():
    response = read_human_input_response({"human_input_response": _text_response(" staging ")})

    assert response is not None
    assert response["value"] == " staging "
