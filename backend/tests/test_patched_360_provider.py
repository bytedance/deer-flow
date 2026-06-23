from types import SimpleNamespace

from deerflow.models import patched_360


class _FakeSkill:
    def __init__(self, name: str, path: str):
        self.name = name
        self._path = path

    def get_container_file_path(self, _base: str) -> str:
        return self._path


def test_extract_tool_call_rewrites_skill_name_to_read_file(monkeypatch):
    monkeypatch.setattr(
        patched_360,
        "get_enabled_skills_for_config",
        lambda _config=None: [_FakeSkill("frontend-design", "/mnt/skills/public/frontend-design/SKILL.md")],
    )
    monkeypatch.setattr(
        patched_360,
        "get_app_config",
        lambda: SimpleNamespace(skills=SimpleNamespace(container_path="/mnt/skills")),
    )

    content = """
<tool_call>
{"name": "frontend-design", "arguments": {"description": "Create a landing page", "parameters": {"layout": "Wide"}}}
</tool_call>
"""

    cleaned, tool_calls = patched_360._extract_tool_calls_from_content(content)

    assert cleaned == ""
    assert tool_calls == [
        {
            "name": "read_file",
            "args": {
                "description": "Create a landing page",
                "path": "/mnt/skills/public/frontend-design/SKILL.md",
            },
            "id": tool_calls[0]["id"],
        }
    ]


def test_extract_tool_call_accepts_skill_alias_suffix(monkeypatch):
    monkeypatch.setattr(
        patched_360,
        "get_enabled_skills_for_config",
        lambda _config=None: [_FakeSkill("ppt-generation", "/mnt/skills/public/ppt-generation/SKILL.md")],
    )
    monkeypatch.setattr(
        patched_360,
        "get_app_config",
        lambda: SimpleNamespace(skills=SimpleNamespace(container_path="/mnt/skills")),
    )

    cleaned, tool_calls = patched_360._extract_tool_calls_from_content(
        '<tool_call>{"name":"_ppt-generation_skill","arguments":{"description":"Make slides"}}</tool_call>'
    )

    assert cleaned == ""
    assert tool_calls[0]["name"] == "read_file"
    assert tool_calls[0]["args"]["path"] == "/mnt/skills/public/ppt-generation/SKILL.md"


def test_extract_tool_call_keeps_real_tool_name():
    cleaned, tool_calls = patched_360._extract_tool_calls_from_content(
        '<tool_call>{"name":"web_search","arguments":{"query":"caren skincare brand"}}</tool_call>'
    )

    assert cleaned == ""
    assert tool_calls[0]["name"] == "web_search"
    assert tool_calls[0]["args"] == {"query": "caren skincare brand"}


def test_normalize_structured_skill_tool_call(monkeypatch):
    monkeypatch.setattr(
        patched_360,
        "get_enabled_skills_for_config",
        lambda _config=None: [_FakeSkill("frontend-design", "/mnt/skills/public/frontend-design/SKILL.md")],
    )
    monkeypatch.setattr(
        patched_360,
        "get_app_config",
        lambda: SimpleNamespace(skills=SimpleNamespace(container_path="/mnt/skills")),
    )

    normalized = patched_360._normalize_tool_calls(
        [
            {
                "name": "frontend-design",
                "args": {
                    "description": "Create a landing page",
                    "parameters": {"layout": "Wide"},
                },
                "id": "call_1",
            }
        ]
    )

    assert normalized == [
        {
            "name": "read_file",
            "args": {
                "description": "Create a landing page",
                "path": "/mnt/skills/public/frontend-design/SKILL.md",
            },
            "id": "call_1",
        }
    ]
