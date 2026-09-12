from deerflow.config.knowledge_base_config import KnowledgeBaseConfig


def test_knowledge_base_config_contains_only_provider_agnostic_capabilities() -> None:
    assert set(KnowledgeBaseConfig.model_fields) == {
        "enabled",
        "scope_selection_enabled",
    }


def test_provider_settings_are_not_retained_in_knowledge_base_config() -> None:
    config = KnowledgeBaseConfig.model_validate(
        {
            "enabled": True,
            "scope_selection_enabled": True,
            "base_url": "http://legacy-ragflow.test",
            "api_key": "legacy-secret",
        }
    )

    assert config.model_dump() == {
        "enabled": True,
        "scope_selection_enabled": True,
    }
