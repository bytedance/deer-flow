from src.config.agent_identity import (
    build_agent_slug,
    build_unique_agent_slug,
    normalize_agent_display_name,
    normalize_agent_slug,
    validate_agent_display_name,
    validate_agent_slug,
)


def test_validate_agent_display_name_accepts_chinese():
    assert validate_agent_display_name("研究助手") == "研究助手"


def test_validate_agent_display_name_rejects_path_separators():
    try:
        validate_agent_display_name("研究/助手")
    except ValueError as exc:
        assert "cannot contain" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_build_agent_slug_uses_ascii_slug_when_possible():
    assert build_agent_slug("Code Reviewer") == "code-reviewer"


def test_build_agent_slug_falls_back_to_stable_hash_for_non_ascii():
    assert build_agent_slug("研究助手") == "agent-347704096c"


def test_build_unique_agent_slug_adds_deterministic_suffix_on_collision():
    assert (
        build_unique_agent_slug(
            "Code Reviewer",
            {"code-reviewer"},
        )
        == "code-reviewer-c10b8b"
    )


def test_normalize_agent_display_name_trims_whitespace():
    assert normalize_agent_display_name("  研究助手  ") == "研究助手"


def test_normalize_agent_slug_lowercases_ascii_slug():
    assert normalize_agent_slug("Code-Reviewer") == "code-reviewer"


def test_validate_agent_slug_rejects_non_ascii_slug():
    try:
        validate_agent_slug("研究助手")
    except ValueError as exc:
        assert "lowercase letters" in str(exc)
    else:
        raise AssertionError("expected ValueError")
