from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from deerflow.agents.middlewares.session_state_middleware import SessionStateMiddleware
from deerflow.config.context_management_config import ContextManagementConfig, SessionStateConfig, set_context_management_config


@pytest.fixture(autouse=True)
def _reset_context_management_config():
    set_context_management_config(ContextManagementConfig())
    yield
    set_context_management_config(ContextManagementConfig())


def test_after_agent_builds_structured_session_state():
    set_context_management_config(ContextManagementConfig(session_state=SessionStateConfig(enabled=True, max_items=2)))
    middleware = SessionStateMiddleware()
    state = {
        "messages": [
            HumanMessage(content="<uploaded_files>\n- file.txt\n</uploaded_files>\n\nInvestigate the parser failure in api.py."),
            AIMessage(content="I inspected the parser and found one likely branch."),
        ],
        "todos": [
            {"content": "Investigate stack trace", "status": "completed"},
            {"content": "Patch parser", "status": "in_progress"},
            {"content": "Add regression test", "status": "pending"},
        ],
        "artifacts": ["/mnt/user-data/outputs/log.txt", "/mnt/user-data/outputs/report.md"],
    }

    result = middleware.after_agent(state, MagicMock())

    assert result is not None
    session_state = result["session_state"]
    assert session_state["current_goal"] == "Investigate the parser failure in api.py."
    assert session_state["task_contract"]["original_request"] == "Investigate the parser failure in api.py."
    assert session_state["active_todos"] == ["[in_progress] Patch parser", "[pending] Add regression test"]
    assert session_state["recent_artifacts"] == ["/mnt/user-data/outputs/log.txt", "/mnt/user-data/outputs/report.md"]
    assert "found one likely branch" in session_state["last_assistant_response"]


def test_after_agent_preserves_original_task_contract_from_first_user_request():
    set_context_management_config(ContextManagementConfig(session_state=SessionStateConfig(enabled=True, max_items=2)))
    middleware = SessionStateMiddleware()
    state = {
        "messages": [
            HumanMessage(
                content="深入研究这个项目，里面有12个章节，仔细研究每个章节，然后生成html报告。"
            ),
            AIMessage(content="I will work through the repo chapter by chapter."),
            HumanMessage(
                content="Here is a summary of the conversation to date: 用户希望我深入研究项目并生成报告。"
            ),
            AIMessage(content="I completed the analysis and prepared a report."),
        ],
        "todos": [],
        "artifacts": [],
    }

    result = middleware.after_agent(state, MagicMock())

    assert result is not None
    session_state = result["session_state"]
    assert session_state["current_goal"] == "深入研究这个项目，里面有12个章节，仔细研究每个章节，然后生成html报告。"
    contract = session_state["task_contract"]
    assert contract["deliverable"] == "HTML report"
    assert contract["output_format"] == "html"
    assert contract["scope"] == "all 12 chapters"
    assert contract["quality_bar"] == "detailed / careful research"
    assert contract["original_request"] == "深入研究这个项目，里面有12个章节，仔细研究每个章节，然后生成html报告。"
    assert contract["active_request"] == "深入研究这个项目，里面有12个章节，仔细研究每个章节，然后生成html报告。"


def test_before_model_injects_session_state_reminder_when_history_is_long():
    set_context_management_config(
        ContextManagementConfig(
            session_state=SessionStateConfig(enabled=True, inject_when_message_count_at_least=3),
        )
    )
    middleware = SessionStateMiddleware()
    state = {
        "messages": [
            HumanMessage(content="One"),
            AIMessage(content="Two"),
            HumanMessage(content="Three"),
        ],
        "session_state": {
            "current_goal": "Finish the refactor",
            "task_contract": {
                "original_request": "Finish the refactor and generate an HTML report.",
                "deliverable": "HTML report",
                "scope": "all 12 chapters",
                "quality_bar": "detailed / careful research",
            },
            "active_todos": ["[in_progress] Update middleware"],
            "recent_artifacts": ["/mnt/user-data/outputs/summary.md"],
            "last_assistant_response": "I narrowed the issue to the agent loop.",
        },
    }

    result = middleware.before_model(state, MagicMock())

    assert result is not None
    reminder = result["messages"][0]
    assert "<session_state>" in reminder.content
    assert "Finish the refactor" in reminder.content
    assert "Deliverable: HTML report" in reminder.content
    assert "Scope: all 12 chapters" in reminder.content
    assert "/mnt/user-data/outputs/summary.md" in reminder.content


def test_before_model_skips_short_histories():
    set_context_management_config(
        ContextManagementConfig(
            session_state=SessionStateConfig(enabled=True, inject_when_message_count_at_least=5),
        )
    )
    middleware = SessionStateMiddleware()
    state = {
        "messages": [HumanMessage(content="short"), AIMessage(content="history")],
        "session_state": {"current_goal": "Stay quiet"},
    }

    assert middleware.before_model(state, MagicMock()) is None


def test_after_agent_ignores_summary_like_human_messages_when_extracting_goal():
    set_context_management_config(ContextManagementConfig(session_state=SessionStateConfig(enabled=True)))
    middleware = SessionStateMiddleware()
    state = {
        "messages": [
            HumanMessage(content="Investigate the repo and produce an HTML report."),
            HumanMessage(name="session_state_collapse", content="<session_history_summary>\nCollapsed history\n</session_history_summary>"),
            HumanMessage(content="Here is a summary of the conversation to date: produce a report."),
            AIMessage(content="I analyzed the repo."),
        ],
        "todos": [],
        "artifacts": [],
    }

    result = middleware.after_agent(state, MagicMock())

    assert result is not None
    assert result["session_state"]["current_goal"] == "Investigate the repo and produce an HTML report."


def test_after_agent_extracts_task_contract_from_block_content_messages():
    set_context_management_config(ContextManagementConfig(session_state=SessionStateConfig(enabled=True)))
    middleware = SessionStateMiddleware()
    state = {
        "messages": [
            HumanMessage(
                content=[
                    {
                        "type": "text",
                        "text": "深入研究这个claudecode的源码解读项目，里面有12个章节，仔细研究每个章节，然后生成html报告",
                    }
                ]
            ),
            AIMessage(content="I cloned the repository and started reading the docs."),
        ],
        "todos": [],
        "artifacts": [],
    }

    result = middleware.after_agent(state, MagicMock())

    assert result is not None
    session_state = result["session_state"]
    assert session_state["current_goal"] == "深入研究这个claudecode的源码解读项目，里面有12个章节，仔细研究每个章节，然后生成html报告"
    assert session_state["task_contract"]["deliverable"] == "HTML report"
    assert session_state["task_contract"]["output_format"] == "html"
    assert session_state["task_contract"]["scope"] == "all 12 chapters"


def test_after_agent_allows_latest_user_requirement_to_override_deliverable_contract():
    set_context_management_config(ContextManagementConfig(session_state=SessionStateConfig(enabled=True)))
    middleware = SessionStateMiddleware()
    state = {
        "messages": [
            HumanMessage(content="深入研究这个项目，先给我一个报告。"),
            AIMessage(content="I will analyze the project."),
            HumanMessage(content="最后必须生成 html 报告文件。"),
            AIMessage(content="I drafted the report in markdown."),
        ],
        "todos": [],
        "artifacts": ["/mnt/user-data/outputs/report.md"],
    }

    result = middleware.after_agent(state, MagicMock())

    assert result is not None
    session_state = result["session_state"]
    assert session_state["current_goal"] == "最后必须生成 html 报告文件。"
    assert session_state["task_contract"]["original_request"] == "深入研究这个项目，先给我一个报告。"
    assert session_state["task_contract"]["active_request"] == "最后必须生成 html 报告文件。"
    assert session_state["task_contract"]["deliverable"] == "HTML report"
    assert session_state["task_contract"]["output_format"] == "html"


def test_after_agent_does_not_create_hard_deliverable_contract_for_incidental_format_mentions():
    set_context_management_config(ContextManagementConfig(session_state=SessionStateConfig(enabled=True)))
    middleware = SessionStateMiddleware()
    state = {
        "messages": [
            HumanMessage(content="Please read this markdown file and inspect this JSON payload and image."),
            AIMessage(content="I inspected the provided files."),
        ],
        "todos": [],
        "artifacts": [],
    }

    result = middleware.after_agent(state, MagicMock())

    assert result is not None
    contract = result["session_state"]["task_contract"]
    assert contract.get("output_format") is None
    assert contract.get("deliverable") is None
    assert contract["must_save_output"] is False
    assert contract["must_present_output"] is False


def test_after_agent_distinguishes_input_format_mentions_from_output_requirements():
    set_context_management_config(ContextManagementConfig(session_state=SessionStateConfig(enabled=True)))
    middleware = SessionStateMiddleware()
    state = {
        "messages": [
            HumanMessage(content="Please read this markdown file first, then generate an HTML report."),
            AIMessage(content="I started by reading the file."),
        ],
        "todos": [],
        "artifacts": [],
    }

    result = middleware.after_agent(state, MagicMock())

    assert result is not None
    contract = result["session_state"]["task_contract"]
    assert contract["output_format"] == "html"
    assert contract["deliverable"] == "HTML report"
    assert contract["must_save_output"] is True
    assert contract["must_present_output"] is True


def test_before_model_surfaces_latest_user_requirement_when_it_differs_from_original_request():
    set_context_management_config(
        ContextManagementConfig(
            session_state=SessionStateConfig(enabled=True, inject_when_message_count_at_least=3),
        )
    )
    middleware = SessionStateMiddleware()
    state = {
        "messages": [
            HumanMessage(content="One"),
            AIMessage(content="Two"),
            HumanMessage(content="Three"),
        ],
        "session_state": {
            "current_goal": "Convert the deliverable to HTML",
            "task_contract": {
                "original_request": "Analyze the repo and write a report.",
                "active_request": "Now convert the final deliverable to HTML.",
                "deliverable": "HTML report",
                "output_format": "html",
            },
        },
    }

    result = middleware.before_model(state, MagicMock())

    assert result is not None
    reminder = result["messages"][0]
    assert "Original request contract: Analyze the repo and write a report." in reminder.content
    assert "Latest user requirement: Now convert the final deliverable to HTML." in reminder.content
    assert "Output format: HTML" in reminder.content


@pytest.mark.parametrize(
    ("request_text", "expected_deliverable", "expected_format"),
    [
        ("请生成 markdown 报告", "Markdown report", "markdown"),
        ("请生成 PPT 演示文稿", "Slide deck", "pptx"),
        ("请输出 Word 文档", "Word document", "docx"),
        ("请生成 PDF 报告", "PDF document", "pdf"),
        ("请生成配图和图片", "Image asset", "image"),
        ("请导出 CSV 数据", "CSV file", "csv"),
        ("请输出 JSON 结果", "JSON file", "json"),
    ],
)
def test_after_agent_extracts_general_output_formats(request_text, expected_deliverable, expected_format):
    set_context_management_config(ContextManagementConfig(session_state=SessionStateConfig(enabled=True)))
    middleware = SessionStateMiddleware()
    state = {
        "messages": [HumanMessage(content=request_text), AIMessage(content="Working on it.")],
        "todos": [],
        "artifacts": [],
    }

    result = middleware.after_agent(state, MagicMock())

    assert result is not None
    contract = result["session_state"]["task_contract"]
    assert contract["deliverable"] == expected_deliverable
    assert contract["output_format"] == expected_format
