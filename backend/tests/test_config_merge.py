from deerflow.config.merge import deep_merge


def test_deep_merge_recursively_overlays_mappings_without_mutating_inputs():
    file_config = {"memory": {"enabled": True, "max_facts": 10}, "models": [{"name": "file"}]}
    code_config = {"memory": {"max_facts": 50}, "models": [{"name": "code"}]}

    result = deep_merge(file_config, code_config)

    assert result == {"memory": {"enabled": True, "max_facts": 50}, "models": [{"name": "code"}]}
    assert file_config["memory"]["max_facts"] == 10
    assert code_config["memory"]["max_facts"] == 50


def test_deep_merge_accepts_no_code_override_and_returns_an_independent_copy():
    file_config = {"title": {"enabled": True}}

    result = deep_merge(file_config, None)
    result["title"]["enabled"] = False

    assert file_config["title"]["enabled"] is True


def test_deep_merge_supports_all_major_app_config_sections():
    file_config = {
        "models": [{"name": "file-model"}],
        "tools": [{"name": "file-tool"}],
        "memory": {"enabled": False, "max_facts": 10},
        "title": {"enabled": True, "max_words": 8},
        "summarization": {"enabled": False, "keep": {"messages": 10}},
        "sandbox": {"use": "file.Provider", "timeout": 60},
    }
    code_config = {
        "models": [{"name": "code-model"}],
        "tools": [{"name": "code-tool"}],
        "memory": {"enabled": True},
        "title": {"max_words": 4},
        "summarization": {"keep": {"messages": 20}},
        "sandbox": {"timeout": 120},
    }

    result = deep_merge(file_config, code_config)

    assert result["models"] == [{"name": "code-model"}]
    assert result["tools"] == [{"name": "code-tool"}]
    assert result["memory"] == {"enabled": True, "max_facts": 10}
    assert result["title"] == {"enabled": True, "max_words": 4}
    assert result["summarization"] == {"enabled": False, "keep": {"messages": 20}}
    assert result["sandbox"] == {"use": "file.Provider", "timeout": 120}
