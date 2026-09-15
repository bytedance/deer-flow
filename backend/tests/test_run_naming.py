from deerflow.runtime.runs.naming import resolve_root_run_name


def test_resolve_root_run_name_from_context_agent_name():
    assert resolve_root_run_name({"context": {"agent_name": "finalis"}}, "lead_agent") == "finalis"


def test_resolve_root_run_name_from_configurable_agent_name():
    assert resolve_root_run_name({"configurable": {"agent_name": "finalis"}}, "lead_agent") == "finalis"


def test_resolve_root_run_name_falls_back_to_assistant_id():
    assert resolve_root_run_name({}, "my-agent") == "my-agent"


def test_resolve_root_run_name_falls_back_to_lead_agent():
    assert resolve_root_run_name({}, None) == "lead_agent"


def test_resolve_root_run_name_prefers_context_over_configurable():
    config = {
        "context": {"agent_name": "ctx-agent"},
        "configurable": {"agent_name": "cfg-agent"},
    }

    assert resolve_root_run_name(config, "lead_agent") == "ctx-agent"


def test_resolve_root_run_name_ignores_blank_agent_name():
    assert resolve_root_run_name({"context": {"agent_name": "   "}}, "my-agent") == "my-agent"


def test_resolve_root_run_name_ignores_non_string_agent_name():
    assert resolve_root_run_name({"context": {"agent_name": None}}, "my-agent") == "my-agent"
