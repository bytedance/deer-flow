from types import SimpleNamespace

from langchain_core.messages import AIMessage, HumanMessage

from src.agents.memory.updater import MemoryUpdater
from src.agents.middlewares.subscription_limits_middleware import SubscriptionLimitsMiddleware
from src.config.memory_config import MemoryConfig
from src.config.subscription_config import (
    SubscriptionConfig,
    SubscriptionTier,
    TierLimitsConfig,
    get_effective_max_memory_facts,
    get_limits_for_subscription,
    get_subscription_config,
    load_subscription_config_from_dict,
    normalize_subscription_tier,
    set_subscription_config,
)


def test_subscription_tier_normalization_and_fallback():
    assert normalize_subscription_tier("solo") == SubscriptionTier.SOLO
    assert normalize_subscription_tier("POWER") == SubscriptionTier.POWER
    assert normalize_subscription_tier(None) == SubscriptionTier.SOLO
    assert normalize_subscription_tier("unknown") == SubscriptionTier.SOLO


def test_subscription_tier_normalization_strict_raises():
    try:
        normalize_subscription_tier("unknown", strict=True)
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "subscription_tier must be one of" in str(exc)


def test_effective_max_memory_facts_respects_global_ceiling():
    assert get_effective_max_memory_facts(500, "solo") == 100
    assert get_effective_max_memory_facts(500, "power") == 250
    assert get_effective_max_memory_facts(500, "team") == 500
    # Global config remains hard upper bound.
    assert get_effective_max_memory_facts(200, "team") == 200


def test_subscription_limits_mapping_values():
    assert get_limits_for_subscription("solo").context_window_tokens == 32000
    assert get_limits_for_subscription("power").context_window_tokens == 64000
    assert get_limits_for_subscription("team").context_window_tokens == 100000


def test_subscription_config_loaded_from_dict():
    """Limits must update at runtime when loaded from config dict (e.g. from config.yaml)."""
    original = get_subscription_config()
    try:
        load_subscription_config_from_dict(
            {
                "solo": {"context_window_tokens": 10000, "max_memory_facts": 5},
                "power": {"context_window_tokens": 20000, "max_memory_facts": 10},
                "team": {"context_window_tokens": 40000, "max_memory_facts": 20},
            }
        )
        assert get_limits_for_subscription("solo").context_window_tokens == 10000
        assert get_limits_for_subscription("solo").max_memory_facts == 5
        assert get_limits_for_subscription("power").context_window_tokens == 20000
        assert get_limits_for_subscription("team").max_memory_facts == 20
    finally:
        set_subscription_config(original)


def test_subscription_config_is_pydantic_model():
    config = SubscriptionConfig()
    assert isinstance(config.solo, TierLimitsConfig)
    assert config.solo.context_window_tokens == 32000
    assert config.solo.max_memory_facts == 100


def test_context_window_middleware_trims_messages_for_solo_tier():
    middleware = SubscriptionLimitsMiddleware()
    runtime = SimpleNamespace(context={"subscription_tier": "solo"})

    # Each long message is ~20k estimated tokens with char/4 heuristic.
    big_text = "x" * 80000
    state = {
        "messages": [
            HumanMessage(content=big_text),
            AIMessage(content=big_text),
            HumanMessage(content=big_text),
        ]
    }

    update = middleware.before_model(state, runtime)

    assert update is not None
    assert len(state["messages"]) < 3
    assert "subscription_context_window_trim" == update["messages"][0].name


def test_context_window_middleware_no_trim_for_power_tier():
    """Two large messages that exceed solo cap but fit within power cap must not be trimmed."""
    middleware = SubscriptionLimitsMiddleware()
    runtime = SimpleNamespace(context={"subscription_tier": "power"})

    big_text = "x" * 80000
    state = {
        "messages": [
            HumanMessage(content=big_text),
            AIMessage(content=big_text),
        ]
    }

    update = middleware.before_model(state, runtime)

    assert update is None
    assert len(state["messages"]) == 2


def test_context_window_middleware_unknown_alias_not_accepted():
    """Transport-level header aliases must not be accepted; unknown keys fall back to solo default."""
    middleware = SubscriptionLimitsMiddleware()
    # Sending under the old aliased header key — should NOT be resolved to power tier.
    runtime = SimpleNamespace(context={"x-subscription-tier": "power"})

    big_text = "x" * 80000
    state = {
        "messages": [
            HumanMessage(content=big_text),
            AIMessage(content=big_text),
        ]
    }

    # Falls back to solo (no subscription_tier key found), so both messages exceed
    # the 32k solo cap and trimming occurs.
    update = middleware.before_model(state, runtime)
    assert update is not None
    assert "subscription_context_window_trim" == update["messages"][0].name


def test_memory_updater_apply_updates_uses_subscription_cap(monkeypatch):
    updater = MemoryUpdater()

    monkeypatch.setattr(
        "src.agents.memory.updater.get_memory_config",
        lambda: MemoryConfig(max_facts=500, backend="postgres", database_url="postgres://test"),
    )

    now_facts = [
        {
            "id": f"fact_{i}",
            "content": f"f{i}",
            "category": "context",
            "confidence": 0.99,
            "createdAt": "2026-03-14T00:00:00Z",
            "source": "t",
        }
        for i in range(220)
    ]
    current_memory = {
        "user": {"workContext": {"summary": "", "updatedAt": ""}, "personalContext": {"summary": "", "updatedAt": ""}, "topOfMind": {"summary": "", "updatedAt": ""}},
        "history": {"recentMonths": {"summary": "", "updatedAt": ""}, "earlierContext": {"summary": "", "updatedAt": ""}, "longTermBackground": {"summary": "", "updatedAt": ""}},
        "facts": now_facts,
    }

    updated = updater._apply_updates(current_memory, update_data={}, thread_id="t1", subscription_tier="solo")
    assert len(updated["facts"]) == 100
