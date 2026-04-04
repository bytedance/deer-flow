from unittest.mock import MagicMock

from langchain_core.messages import AIMessage, HumanMessage

from deerflow.agents.middlewares.deliverable_guard_middleware import DeliverableGuardMiddleware


def test_after_model_injects_reminder_when_deliverable_file_missing():
    middleware = DeliverableGuardMiddleware()
    state = {
        "messages": [
            HumanMessage(content="Research all 12 chapters and generate an HTML report."),
            AIMessage(content="Here are the first three chapters."),
        ],
        "artifacts": [],
        "session_state": {
            "task_contract": {
                "deliverable": "HTML report",
                "output_format": "html",
                "must_save_output": True,
                "must_present_output": True,
            }
        },
    }

    result = middleware.after_model(state, MagicMock())

    assert result is not None
    reminder = result["messages"][0]
    assert "Required deliverable: HTML report" in reminder.content
    assert "present_files" in reminder.content


def test_after_model_derives_contract_from_first_turn_when_session_state_not_persisted_yet():
    middleware = DeliverableGuardMiddleware()
    state = {
        "messages": [
            HumanMessage(content="深入研究这个项目的12个章节，并生成 HTML 报告。"),
            AIMessage(content="I finished the research report."),
        ],
        "artifacts": ["/mnt/user-data/outputs/report.md"],
        "todos": [],
    }

    result = middleware.after_model(state, MagicMock())

    assert result is not None
    reminder = result["messages"][0]
    assert "Required deliverable: HTML report" in reminder.content
    assert "present_files" in reminder.content


def test_after_model_skips_when_artifact_is_already_presented():
    middleware = DeliverableGuardMiddleware()
    state = {
        "messages": [
            HumanMessage(content="Research all 12 chapters and generate an HTML report."),
            AIMessage(content="The report is ready."),
        ],
        "artifacts": ["/mnt/user-data/outputs/report.html"],
        "session_state": {
            "task_contract": {
                "deliverable": "HTML report",
                "output_format": "html",
                "must_save_output": True,
                "must_present_output": True,
            }
        },
    }

    assert middleware.after_model(state, MagicMock()) is None


def test_after_model_keeps_guarding_when_only_markdown_artifact_exists_for_html_contract():
    middleware = DeliverableGuardMiddleware()
    state = {
        "messages": [
            HumanMessage(content="Research all 12 chapters and generate an HTML report."),
            AIMessage(content="The report is ready."),
        ],
        "artifacts": ["/mnt/user-data/outputs/report.md"],
        "session_state": {
            "task_contract": {
                "deliverable": "HTML report",
                "output_format": "html",
                "must_save_output": True,
                "must_present_output": True,
            }
        },
    }

    result = middleware.after_model(state, MagicMock())

    assert result is not None
    reminder = result["messages"][0]
    assert "Required deliverable: HTML report" in reminder.content


def test_after_model_skips_when_model_is_still_calling_tools():
    middleware = DeliverableGuardMiddleware()
    state = {
        "messages": [
            HumanMessage(content="Generate an HTML report."),
            AIMessage(content="", tool_calls=[{"name": "bash", "id": "call-1", "args": {}}]),
        ],
        "artifacts": [],
        "session_state": {
            "task_contract": {
                "deliverable": "HTML report",
                "output_format": "html",
                "must_save_output": True,
                "must_present_output": True,
            }
        },
    }

    assert middleware.after_model(state, MagicMock()) is None


def test_after_model_skips_when_markdown_contract_has_markdown_artifact():
    middleware = DeliverableGuardMiddleware()
    state = {
        "messages": [
            HumanMessage(content="Generate a markdown report."),
            AIMessage(content="The report is ready."),
        ],
        "artifacts": ["/mnt/user-data/outputs/report.md"],
        "session_state": {
            "task_contract": {
                "deliverable": "Markdown report",
                "output_format": "markdown",
                "must_save_output": True,
                "must_present_output": True,
            }
        },
    }

    assert middleware.after_model(state, MagicMock()) is None


def test_after_model_keeps_guarding_when_ppt_contract_only_has_markdown_artifact():
    middleware = DeliverableGuardMiddleware()
    state = {
        "messages": [
            HumanMessage(content="Generate a PPT deck."),
            AIMessage(content="The deck is ready."),
        ],
        "artifacts": ["/mnt/user-data/outputs/report.md"],
        "session_state": {
            "task_contract": {
                "deliverable": "Slide deck",
                "output_format": "pptx",
                "must_save_output": True,
                "must_present_output": True,
            }
        },
    }

    result = middleware.after_model(state, MagicMock())

    assert result is not None
    assert "Required deliverable: Slide deck" in result["messages"][0].content


def test_after_model_rechecks_contract_after_prior_guard_reminder():
    middleware = DeliverableGuardMiddleware()
    state = {
        "messages": [
            HumanMessage(content="Research all 12 chapters and generate an HTML report."),
            AIMessage(content="Here is the report summary."),
            HumanMessage(content="<deliverable_guard>\nThe task contract is not complete yet.\n</deliverable_guard>"),
            AIMessage(content="I have now fully finished the report."),
        ],
        "artifacts": ["/mnt/user-data/outputs/report.md"],
        "session_state": {
            "task_contract": {
                "deliverable": "HTML report",
                "output_format": "html",
                "must_save_output": True,
                "must_present_output": True,
            }
        },
    }

    result = middleware.after_model(state, MagicMock())

    assert result is not None
    assert "Required deliverable: HTML report" in result["messages"][0].content
