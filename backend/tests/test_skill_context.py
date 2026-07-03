from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from deerflow.agents.middlewares.skill_context import extract_skills, render_skill_context

_ROOT = "/mnt/skills"
_READ = frozenset({"read_file", "read", "view", "cat"})
_SKILL_BODY = """---
name: data-analysis
description: Analyze data with pandas and charts.
---
# Data Analysis
Use pandas. ALWAYS_USE_PANDAS_SENTINEL
"""


def _ai_read(tool_call_id: str, path: str, name: str = "read_file") -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": {"path": path}, "id": tool_call_id, "type": "tool_call"}],
    )


class TestExtractSkills:
    def test_captures_skill_reference_with_description(self):
        msgs = [
            HumanMessage(content="use the analysis skill"),
            _ai_read("r1", "/mnt/skills/public/data-analysis/SKILL.md"),
            ToolMessage(content=_SKILL_BODY, tool_call_id="r1", id="tm1"),
        ]
        out = extract_skills(msgs, skills_root=_ROOT, read_tool_names=_READ)
        assert len(out) == 1
        assert out[0]["name"] == "data-analysis"
        assert out[0]["path"] == "/mnt/skills/public/data-analysis/SKILL.md"
        assert out[0]["description"] == "Analyze data with pandas and charts."
        assert "content" not in out[0]
        assert "ALWAYS_USE_PANDAS_SENTINEL" not in repr(out[0])
        assert isinstance(out[0]["loaded_at"], int)

    def test_description_is_capped_at_capture_time(self):
        body = "---\nname: huge\ndescription: " + ("x" * 2000) + "\n---\nBODY_SENTINEL"
        msgs = [
            _ai_read("r1", "/mnt/skills/public/huge/SKILL.md"),
            ToolMessage(content=body, tool_call_id="r1", id="tm1"),
        ]

        out = extract_skills(msgs, skills_root=_ROOT, read_tool_names=_READ)

        assert out
        assert len(out[0]["description"]) <= 500
        assert "BODY_SENTINEL" not in repr(out[0])

    def test_missing_frontmatter_yields_empty_description(self):
        msgs = [
            _ai_read("r1", "/mnt/skills/public/x/SKILL.md"),
            ToolMessage(content="# X\nno frontmatter here", tool_call_id="r1", id="tm1"),
        ]
        out = extract_skills(msgs, skills_root=_ROOT, read_tool_names=_READ)
        assert out and out[0]["description"] == ""

    def test_malformed_frontmatter_yields_empty_description(self):
        msgs = [
            _ai_read("r1", "/mnt/skills/public/x/SKILL.md"),
            ToolMessage(content="---\n: : not valid yaml\n---\nbody", tool_call_id="r1", id="tm1"),
        ]
        out = extract_skills(msgs, skills_root=_ROOT, read_tool_names=_READ)
        assert out and out[0]["description"] == ""

    def test_normalizes_dot_segments_under_skills_root(self):
        msgs = [
            _ai_read("r1", "/mnt/skills/public/./data-analysis/SKILL.md"),
            ToolMessage(content="body", tool_call_id="r1", id="tm1"),
        ]

        out = extract_skills(msgs, skills_root="/mnt/skills/", read_tool_names=_READ)

        assert out and out[0]["path"] == "/mnt/skills/public/data-analysis/SKILL.md"
        assert out[0]["name"] == "data-analysis"

    def test_rejects_traversal_that_escapes_skills_root(self):
        msgs = [
            _ai_read("r1", "/mnt/skills/../workspace/secrets.txt"),
            ToolMessage(content="secret", tool_call_id="r1", id="tm1"),
        ]

        assert extract_skills(msgs, skills_root=_ROOT, read_tool_names=_READ) == []

    def test_ignores_supporting_resources_under_skill_directory(self):
        msgs = [
            _ai_read("r1", "/mnt/skills/public/data-analysis/scripts/analyze.py"),
            ToolMessage(content="large script body", tool_call_id="r1", id="tm1"),
        ]

        assert extract_skills(msgs, skills_root=_ROOT, read_tool_names=_READ) == []

    def test_ignores_error_tool_messages(self):
        msgs = [
            _ai_read("r1", "/mnt/skills/public/data-analysis/SKILL.md"),
            ToolMessage(content="Error: File not found", tool_call_id="r1", id="tm1", status="error"),
        ]

        assert extract_skills(msgs, skills_root=_ROOT, read_tool_names=_READ) == []

    def test_ignores_read_file_error_text_even_when_tool_status_is_success(self):
        msgs = [
            _ai_read("r1", "/mnt/skills/public/missing/SKILL.md"),
            ToolMessage(content="Error: File not found: /mnt/skills/public/missing/SKILL.md", tool_call_id="r1", id="tm1"),
        ]

        assert extract_skills(msgs, skills_root=_ROOT, read_tool_names=_READ) == []

    def test_ignores_reads_outside_skills_root(self):
        msgs = [
            _ai_read("r1", "/workspace/notes.md"),
            ToolMessage(content="notes", tool_call_id="r1", id="tm1"),
        ]
        assert extract_skills(msgs, skills_root=_ROOT, read_tool_names=_READ) == []

    def test_ignores_non_read_tool_names(self):
        msgs = [
            _ai_read("r1", "/mnt/skills/a/SKILL.md", name="write_file"),
            ToolMessage(content="x", tool_call_id="r1", id="tm1"),
        ]
        assert extract_skills(msgs, skills_root=_ROOT, read_tool_names=_READ) == []

    def test_read_without_result_is_skipped(self):
        msgs = [_ai_read("r1", "/mnt/skills/a/SKILL.md")]
        assert extract_skills(msgs, skills_root=_ROOT, read_tool_names=_READ) == []

    def test_trailing_slash_root_normalized(self):
        msgs = [
            _ai_read("r1", "/mnt/skills/public/a/SKILL.md"),
            ToolMessage(content="body", tool_call_id="r1", id="tm1"),
        ]
        out = extract_skills(msgs, skills_root="/mnt/skills/", read_tool_names=_READ)
        assert out and out[0]["name"] == "a"

    def test_multiple_skills_each_captured(self):
        msgs = [
            _ai_read("r1", "/mnt/skills/public/a/SKILL.md"),
            ToolMessage(content="A", tool_call_id="r1", id="tm1"),
            _ai_read("r2", "/mnt/skills/custom/b/SKILL.md"),
            ToolMessage(content="B", tool_call_id="r2", id="tm2"),
        ]
        out = extract_skills(msgs, skills_root=_ROOT, read_tool_names=_READ)
        assert [e["name"] for e in out] == ["a", "b"]


class TestRenderSkillContext:
    def test_empty_returns_empty_string(self):
        assert render_skill_context([]) == ""

    def test_renders_reference_reminder_not_body(self):
        entries = [
            {
                "name": "data-analysis",
                "path": "/mnt/skills/public/data-analysis/SKILL.md",
                "description": "Analyze data with pandas.",
                "loaded_at": 2,
            }
        ]
        out = render_skill_context(entries)
        assert "Active skills" in out
        assert "re-read" in out.lower()
        assert "data-analysis" in out
        assert "Analyze data with pandas." in out
        assert "/mnt/skills/public/data-analysis/SKILL.md" in out
        assert "###" not in out

    def test_entry_without_description_still_renders_name_and_path(self):
        entries = [{"name": "x", "path": "/mnt/skills/public/x/SKILL.md", "description": "", "loaded_at": 0}]
        out = render_skill_context(entries)
        assert "- x" in out
        assert "/mnt/skills/public/x/SKILL.md" in out

    def test_render_caps_legacy_large_description(self):
        entries = [{"name": "x", "path": "/mnt/skills/public/x/SKILL.md", "description": "x" * 2000, "loaded_at": 0}]

        out = render_skill_context(entries)

        assert len(out) < 800
