"""Tests for the GitHub webhook fan-out helper.

We do not exercise the full agent run here — that path now lives in the
ChannelManager and is covered by integration tests. These tests verify
the fan-out logic: bot-loop prevention, target extraction, registry
lookup, trigger filtering, and that one InboundMessage with the right
shape lands on the bus per matching binding.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.channels.message_bus import InboundMessage, MessageBus
from app.gateway.github.dispatcher import fanout_event


def _write_agent(base: Path, user_id: str, name: str, body: dict) -> Path:
    agent_dir = base / "users" / user_id / "agents" / name
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "config.yaml").write_text(yaml.safe_dump(body), encoding="utf-8")
    return agent_dir


@pytest.fixture()
def base_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    from deerflow.config import paths as paths_module

    monkeypatch.setattr(paths_module, "_paths", None)
    # Each test uses a fresh tmp_path, so the registry's mtime cache from
    # a prior test would short-circuit the scan and return [] — drop it.
    from app.gateway.github.registry import _invalidate_cache

    _invalidate_cache()
    return tmp_path


async def _drain(bus: MessageBus) -> list[InboundMessage]:
    out: list[InboundMessage] = []
    while not bus.inbound_queue.empty():
        out.append(await bus.get_inbound())
    return out


# ---------------------------------------------------------------------------
# Bot-loop prevention — per-agent self-event gate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_self_event_skips_the_owning_agent_only(base_dir: Path) -> None:
    """Events sent by an agent's own bot account skip THAT agent only.

    The reviewer (whose ``mention_login`` is ``llm-gateway-ai``) must not
    re-trigger on its own comment. The coder (different identity) should
    still fire on the same event if its triggers match.
    """
    bus = MessageBus()
    _write_agent(
        base_dir,
        "default",
        "reviewer-llm-gateway",
        {
            "name": "reviewer-llm-gateway",
            "github": {
                "bindings": [
                    {
                        "repo": "zhfeng/llm-gateway",
                        "triggers": {
                            "issue_comment": {
                                "require_mention": True,
                                "mention_login": "llm-gateway-ai",
                            }
                        },
                    }
                ],
            },
        },
    )
    _write_agent(
        base_dir,
        "default",
        "coding-llm-gateway",
        {
            "name": "coding-llm-gateway",
            "github": {
                "bindings": [
                    {
                        "repo": "zhfeng/llm-gateway",
                        "triggers": {
                            "issue_comment": {
                                "require_mention": True,
                                "mention_login": "coding-llm-gateway-ai",
                            }
                        },
                    }
                ],
            },
        },
    )
    payload = {
        "action": "created",
        "issue": {"number": 5, "pull_request": {"url": "..."}},
        "comment": {
            "body": "Following up @coding-llm-gateway-ai please address this.",
            "user": {"login": "llm-gateway-ai[bot]"},
        },
        "repository": {"full_name": "zhfeng/llm-gateway"},
        "sender": {"login": "llm-gateway-ai[bot]"},
    }
    result = await fanout_event(bus, "issue_comment", "del-self", payload)
    # Reviewer matched but skipped — sender is its own identity.
    assert "reviewer-llm-gateway" in result["matched_agents"]
    assert "reviewer-llm-gateway" not in result["fired_agents"]
    assert any(s["agent"] == "reviewer-llm-gateway" and s["reason"] == "self_event" for s in result["skipped"])
    # Coder fires — same event, different self-identity.
    assert "coding-llm-gateway" in result["fired_agents"]
    messages = await _drain(bus)
    assert len(messages) == 1
    assert messages[0].metadata["agent_name"] == "coding-llm-gateway"


@pytest.mark.asyncio
async def test_third_party_bot_events_are_not_skipped(base_dir: Path) -> None:
    """Events from other bots (Copilot, CodeRabbit, …) must reach the agents.

    The old all-bots short-circuit blocked these as a side effect; the new
    per-agent self-event gate only fires when ``sender.login`` matches the
    agent's own identity.
    """
    bus = MessageBus()
    _write_agent(
        base_dir,
        "default",
        "reviewer-llm-gateway",
        {
            "name": "reviewer-llm-gateway",
            "github": {
                "bindings": [
                    {
                        "repo": "zhfeng/llm-gateway",
                        "triggers": {
                            "issue_comment": {
                                "require_mention": True,
                                "mention_login": "llm-gateway-ai",
                            }
                        },
                    }
                ],
            },
        },
    )
    payload = {
        "action": "created",
        "issue": {"number": 9, "pull_request": {"url": "..."}},
        "comment": {
            "body": "Hey @llm-gateway-ai, here is my review.",
            "user": {"login": "Copilot"},
        },
        "repository": {"full_name": "zhfeng/llm-gateway"},
        "sender": {"login": "Copilot", "type": "Bot"},
    }
    result = await fanout_event(bus, "issue_comment", "del-copilot", payload)
    assert "reviewer-llm-gateway" in result["fired_agents"]
    assert result["skipped"] == []
    messages = await _drain(bus)
    assert len(messages) == 1
    assert messages[0].metadata["agent_name"] == "reviewer-llm-gateway"


@pytest.mark.asyncio
async def test_agent_name_is_only_a_fallback_when_no_explicit_identity_is_set(base_dir: Path) -> None:
    """``agent.name`` must NOT be in the self-identity set when ``bot_login``
    or any ``mention_login`` is configured.

    Otherwise a real GitHub user whose login happens to equal an agent's
    directory name (``reviewer``, ``coder``, ``bot`` — all valid GitHub
    logins) would be silently dropped. The fallback only kicks in when the
    operator gave us nothing more specific.
    """
    bus = MessageBus()
    # Agent named ``reviewer`` with an explicit bot_login that differs.
    _write_agent(
        base_dir,
        "default",
        "reviewer",
        {
            "name": "reviewer",
            "github": {
                "bot_login": "reviewer-app-bot",
                "bindings": [
                    {
                        "repo": "a/b",
                        "triggers": {"pull_request": {"actions": ["opened"]}},
                    }
                ],
            },
        },
    )
    # Real human user with login ``reviewer`` opens a PR.
    payload = {
        "action": "opened",
        "pull_request": {"number": 1, "user": {"login": "reviewer"}, "title": "Fix typo", "body": ""},
        "repository": {"full_name": "a/b"},
        "sender": {"login": "reviewer"},
    }
    result = await fanout_event(bus, "pull_request", "del-collision", payload)
    # The agent must fire — the human's login collides with the agent
    # directory name, but ``bot_login`` is the only true self-identity.
    assert result["fired_agents"] == ["reviewer"]
    assert result["skipped"] == []


@pytest.mark.asyncio
async def test_agent_name_fallback_still_works_with_no_explicit_identity(base_dir: Path) -> None:
    """When no bot_login / mention_login is set, agent.name IS the self-identity.

    Preserves the safety net for the simplest config — an agent that just
    posts as ``@<agent-name>`` without configuring anything else still
    avoids re-triggering itself.
    """
    bus = MessageBus()
    _write_agent(
        base_dir,
        "default",
        "solo-bot",
        {
            "name": "solo-bot",
            "github": {
                "bindings": [{"repo": "a/b", "triggers": {"pull_request": {"actions": ["opened"]}}}],
            },
        },
    )
    payload = {
        "action": "opened",
        "pull_request": {"number": 2, "user": {"login": "solo-bot"}, "title": "x", "body": ""},
        "repository": {"full_name": "a/b"},
        "sender": {"login": "solo-bot[bot]"},
    }
    result = await fanout_event(bus, "pull_request", "del-solo", payload)
    assert result["fired_agents"] == []
    assert any(s["reason"] == "self_event" for s in result["skipped"])


# ---------------------------------------------------------------------------
# Events without targets
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ping_returns_no_target(base_dir: Path) -> None:
    bus = MessageBus()
    result = await fanout_event(bus, "ping", "del-1", {"zen": "x"})
    assert result["matched_agents"] == []
    assert any(r["reason"] == "no_target" for r in result["skipped"])
    assert await _drain(bus) == []


# ---------------------------------------------------------------------------
# No matching agents
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_matching_agents_returns_empty(base_dir: Path) -> None:
    bus = MessageBus()
    payload = {
        "action": "opened",
        "pull_request": {"number": 1, "user": {"login": "zhfeng"}},
        "repository": {"full_name": "a/b"},
    }
    result = await fanout_event(bus, "pull_request", "del-1", payload)
    assert result == {"matched_agents": [], "fired_agents": [], "skipped": []}
    assert await _drain(bus) == []


@pytest.mark.asyncio
async def test_matching_agent_for_different_repo_skips(base_dir: Path) -> None:
    bus = MessageBus()
    _write_agent(
        base_dir,
        "default",
        "bot",
        {
            "name": "bot",
            "github": {"bindings": [{"repo": "other/repo"}]},
        },
    )
    payload = {
        "action": "opened",
        "pull_request": {"number": 1, "user": {"login": "zhfeng"}},
        "repository": {"full_name": "a/b"},
    }
    result = await fanout_event(bus, "pull_request", "del-1", payload)
    assert result == {"matched_agents": [], "fired_agents": [], "skipped": []}
    assert await _drain(bus) == []


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pull_request_opened_fires_and_publishes(base_dir: Path) -> None:
    bus = MessageBus()
    _write_agent(
        base_dir,
        "default",
        "reviewer",
        {
            "name": "reviewer",
            "github": {
                "installation_id": 1234,
                "bindings": [
                    {
                        "repo": "zhfeng/llm-gateway",
                        "triggers": {"pull_request": {"actions": ["opened"]}},
                    }
                ],
            },
        },
    )
    payload = {
        "action": "opened",
        "pull_request": {
            "number": 7,
            "title": "Add feature",
            "user": {"login": "zhfeng"},
            "body": "This is my change.",
        },
        "repository": {"full_name": "zhfeng/llm-gateway"},
        "sender": {"login": "zhfeng"},
    }
    result = await fanout_event(bus, "pull_request", "del-abc", payload)
    assert result["matched_agents"] == ["reviewer"]
    assert result["fired_agents"] == ["reviewer"]
    assert result["skipped"] == []

    messages = await _drain(bus)
    assert len(messages) == 1
    msg = messages[0]
    assert msg.channel_name == "github"
    assert msg.chat_id == "zhfeng/llm-gateway"
    # topic_id pairs the PR number with the agent name so the
    # ChannelStore key separates per-agent threads on the same PR.
    assert msg.topic_id == "7:reviewer"
    assert msg.user_id == "zhfeng"
    assert msg.owner_user_id == "default"
    assert "Add feature" in msg.text
    assert msg.metadata["agent_name"] == "reviewer"
    gh = msg.metadata["github"]
    assert gh["repo"] == "zhfeng/llm-gateway"
    assert gh["number"] == 7
    assert gh["installation_id"] == 1234
    assert gh["event"] == "pull_request"
    assert gh["delivery_id"] == "del-abc"
    # recursion_limit defaults to None when the agent doesn't set one;
    # ChannelManager._resolve_run_params falls back to the channel default
    # (250) in that case.
    assert gh["recursion_limit"] is None
    # Deterministic thread id is surfaced as preferred_thread_id so the
    # manager's first-create path pins the LangGraph thread to it.
    assert msg.metadata["preferred_thread_id"] == gh["thread_id"]
    assert msg.metadata["preferred_thread_id"]  # non-empty


@pytest.mark.asyncio
async def test_per_agent_recursion_limit_flows_through_metadata(base_dir: Path) -> None:
    """An agent's ``github.recursion_limit`` is ferried to ChannelManager.

    This is the bridge between the YAML config field and the actual
    ``run_config["recursion_limit"]`` the manager hands LangGraph: the
    dispatcher reads it from the binding at fanout time and stashes it
    in ``msg.metadata["github"]["recursion_limit"]`` so the manager
    doesn't need to re-load the AgentConfig per delivery.
    """
    bus = MessageBus()
    _write_agent(
        base_dir,
        "default",
        "refactorer",
        {
            "name": "refactorer",
            "github": {
                "installation_id": 1234,
                "recursion_limit": 500,
                "bindings": [
                    {
                        "repo": "owner/big-repo",
                        "triggers": {"pull_request": {"actions": ["opened"]}},
                    }
                ],
            },
        },
    )
    payload = {
        "action": "opened",
        "pull_request": {"number": 1, "user": {"login": "zhfeng"}, "title": "x", "body": ""},
        "repository": {"full_name": "owner/big-repo"},
        "sender": {"login": "zhfeng"},
    }
    await fanout_event(bus, "pull_request", "del-rl", payload)
    messages = await _drain(bus)
    assert len(messages) == 1
    assert messages[0].metadata["github"]["recursion_limit"] == 500


@pytest.mark.asyncio
async def test_issue_comment_with_mention_fires(base_dir: Path) -> None:
    bus = MessageBus()
    _write_agent(
        base_dir,
        "default",
        "assistant",
        {
            "name": "assistant",
            "github": {
                "bindings": [
                    {
                        "repo": "zhfeng/llm-gateway",
                        "triggers": {
                            "issue_comment": {
                                "require_mention": True,
                                "mention_login": "assistant",
                            }
                        },
                    }
                ],
            },
        },
    )
    payload = {
        "action": "created",
        "issue": {"number": 11, "pull_request": {"url": "..."}},
        "comment": {
            "body": "Hey @assistant can you review this?",
            "user": {"login": "zhfeng"},
        },
        "repository": {"full_name": "zhfeng/llm-gateway"},
        "sender": {"login": "zhfeng"},
    }
    result = await fanout_event(bus, "issue_comment", "del-def", payload)
    assert "assistant" in result["fired_agents"]
    messages = await _drain(bus)
    assert len(messages) == 1
    assert messages[0].metadata["agent_name"] == "assistant"


@pytest.mark.asyncio
async def test_issue_comment_without_mention_skipped(base_dir: Path) -> None:
    bus = MessageBus()
    _write_agent(
        base_dir,
        "default",
        "bot",
        {
            "name": "bot",
            "github": {
                "bindings": [
                    {
                        "repo": "a/b",
                        "triggers": {"issue_comment": {"require_mention": True}},
                    }
                ],
            },
        },
    )
    payload = {
        "action": "created",
        "issue": {"number": 2, "pull_request": {"url": "..."}},
        "comment": {"body": "general chat without mention", "user": {"login": "alice"}},
        "repository": {"full_name": "a/b"},
        "sender": {"login": "alice"},
    }
    result = await fanout_event(bus, "issue_comment", "del-xyz", payload)
    assert result["fired_agents"] == []
    assert len(result["skipped"]) == 1
    assert "mention" in result["skipped"][0]["reason"]
    assert await _drain(bus) == []


@pytest.mark.asyncio
async def test_require_mention_uses_bot_login_when_trigger_omits_mention_login(base_dir: Path) -> None:
    """Regression pin for willem-bd's finding #2 on PR #3754.

    Mention gating must default to ``github.bot_login`` (the App's
    @-handle, the same identity used by the self-event gate), not to the
    agent's directory name. Previously this fell back to ``agent.name``,
    so an operator who set ``github.bot_login: deerflow-bot`` on an agent
    whose directory was named ``coder`` would see every legitimate
    ``@deerflow-bot`` mention rejected with ``mention required for @coder``
    — the two gates disagreed on identity.
    """
    bus = MessageBus()
    _write_agent(
        base_dir,
        "default",
        "coder",  # agent directory name differs from the App's bot handle
        {
            "name": "coder",
            "github": {
                "bot_login": "deerflow-bot",
                "bindings": [
                    {
                        "repo": "a/b",
                        # No per-trigger mention_login override — the
                        # default fallback path is what is under test.
                        "triggers": {"issue_comment": {"require_mention": True}},
                    }
                ],
            },
        },
    )

    # Mentioning the configured bot_login should fire the agent.
    mention_payload = {
        "action": "created",
        "issue": {"number": 7, "pull_request": {"url": "..."}},
        "comment": {"body": "hey @deerflow-bot please look at this", "user": {"login": "alice"}},
        "repository": {"full_name": "a/b"},
        "sender": {"login": "alice"},
    }
    result = await fanout_event(bus, "issue_comment", "del-bot-mention", mention_payload)
    assert result["fired_agents"] == ["coder"], result
    drained = await _drain(bus)
    assert len(drained) == 1

    # Mentioning the agent's directory name (the previous fallback) must
    # NOT fire — that was the exact misbehaviour reported.
    bus_2 = MessageBus()
    dirname_payload = {
        **mention_payload,
        "comment": {"body": "hey @coder look at this", "user": {"login": "alice"}},
    }
    result_2 = await fanout_event(bus_2, "issue_comment", "del-dir-mention", dirname_payload)
    assert result_2["fired_agents"] == [], result_2
    assert len(result_2["skipped"]) == 1
    assert "mention required for @deerflow-bot" in result_2["skipped"][0]["reason"]


@pytest.mark.asyncio
async def test_require_mention_falls_back_to_agent_name_when_no_bot_login(base_dir: Path) -> None:
    """When ``github.bot_login`` is unset, the agent's directory name is the
    fallback — matching the precedence the self-event gate uses. This
    preserves the existing behaviour for agents that never configured a
    distinct App identity.
    """
    bus = MessageBus()
    _write_agent(
        base_dir,
        "default",
        "assistant",
        {
            "name": "assistant",
            "github": {
                # No bot_login here.
                "bindings": [
                    {
                        "repo": "a/b",
                        "triggers": {"issue_comment": {"require_mention": True}},
                    }
                ],
            },
        },
    )
    payload = {
        "action": "created",
        "issue": {"number": 9, "pull_request": {"url": "..."}},
        "comment": {"body": "hey @assistant please look", "user": {"login": "alice"}},
        "repository": {"full_name": "a/b"},
        "sender": {"login": "alice"},
    }
    result = await fanout_event(bus, "issue_comment", "del-fallback", payload)
    assert result["fired_agents"] == ["assistant"], result


# ---------------------------------------------------------------------------
# Operator-set default mention login (R8 — channels.github.default_mention_login)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_operator_default_mention_login_used_when_agent_omits_bot_login(base_dir: Path) -> None:
    """Regression pin for willem-bd's R8 on PR #3754.

    CLAUDE.md documents ``channels.github.default_mention_login`` as the
    global default for ``require_mention`` triggers. When neither the
    trigger nor the agent's ``github.bot_login`` sets a handle, this
    operator-set default must be used as the fallback — *before* the
    agent's directory name. Previously the chain skipped this step
    entirely, so an operator setting ``default_mention_login:
    deerflow-bot`` saw mentions still gated on ``@coder`` (the agent's
    directory name).
    """
    bus = MessageBus()
    _write_agent(
        base_dir,
        "default",
        "coder",
        {
            "name": "coder",
            "github": {
                # No bot_login — exercises the operator-default branch.
                "bindings": [
                    {"repo": "a/b", "triggers": {"issue_comment": {"require_mention": True}}},
                ],
            },
        },
    )

    # @deerflow-bot (the configured operator default) must fire.
    fire_payload = {
        "action": "created",
        "issue": {"number": 7, "pull_request": {"url": "..."}},
        "comment": {"body": "hey @deerflow-bot please look", "user": {"login": "alice"}},
        "repository": {"full_name": "a/b"},
        "sender": {"login": "alice"},
    }
    result = await fanout_event(
        bus,
        "issue_comment",
        "del-opdef-fire",
        fire_payload,
        operator_default_mention_login="deerflow-bot",
    )
    assert result["fired_agents"] == ["coder"], result

    # @coder (the agent-name last-resort fallback) must NOT fire when an
    # operator default is configured — the operator's intent wins.
    bus_2 = MessageBus()
    skip_payload = {
        **fire_payload,
        "comment": {"body": "hey @coder look", "user": {"login": "alice"}},
    }
    result_2 = await fanout_event(
        bus_2,
        "issue_comment",
        "del-opdef-skip",
        skip_payload,
        operator_default_mention_login="deerflow-bot",
    )
    assert result_2["fired_agents"] == [], result_2
    assert "mention required for @deerflow-bot" in result_2["skipped"][0]["reason"]


@pytest.mark.asyncio
async def test_agent_bot_login_outranks_operator_default(base_dir: Path) -> None:
    """Per-agent ``github.bot_login`` outranks the global operator default.

    An agent that opts into its own App identity is the authority for its
    own mention handle. The operator default is the *fallback* for agents
    that haven't configured one — it must not override the per-agent
    setting (otherwise distinct App-per-agent deployments break).
    """
    bus = MessageBus()
    _write_agent(
        base_dir,
        "default",
        "reviewer",
        {
            "name": "reviewer",
            "github": {
                "bot_login": "reviewer-bot",  # per-agent identity
                "bindings": [
                    {"repo": "a/b", "triggers": {"issue_comment": {"require_mention": True}}},
                ],
            },
        },
    )

    # The operator default is set, but per-agent bot_login wins.
    fire_payload = {
        "action": "created",
        "issue": {"number": 7, "pull_request": {"url": "..."}},
        "comment": {"body": "hey @reviewer-bot please review", "user": {"login": "alice"}},
        "repository": {"full_name": "a/b"},
        "sender": {"login": "alice"},
    }
    result = await fanout_event(
        bus,
        "issue_comment",
        "del-perbot",
        fire_payload,
        operator_default_mention_login="deerflow-bot",
    )
    assert result["fired_agents"] == ["reviewer"], result

    # Mentioning the operator default while the agent has its own bot_login
    # must NOT fire — the operator default is irrelevant here.
    bus_2 = MessageBus()
    miss_payload = {
        **fire_payload,
        "comment": {"body": "hey @deerflow-bot review please", "user": {"login": "alice"}},
    }
    result_2 = await fanout_event(
        bus_2,
        "issue_comment",
        "del-perbot-skip",
        miss_payload,
        operator_default_mention_login="deerflow-bot",
    )
    assert result_2["fired_agents"] == [], result_2
    assert "mention required for @reviewer-bot" in result_2["skipped"][0]["reason"]


@pytest.mark.asyncio
async def test_trigger_mention_login_outranks_operator_default(base_dir: Path) -> None:
    """Per-trigger ``mention_login`` is the most specific override — it
    must outrank both ``github.bot_login`` and the operator default.
    """
    bus = MessageBus()
    _write_agent(
        base_dir,
        "default",
        "agent-x",
        {
            "name": "agent-x",
            "github": {
                "bot_login": "agent-x-bot",
                "bindings": [
                    {
                        "repo": "a/b",
                        # Per-trigger override — most specific wins.
                        "triggers": {
                            "issue_comment": {
                                "require_mention": True,
                                "mention_login": "trigger-handle",
                            }
                        },
                    },
                ],
            },
        },
    )
    payload = {
        "action": "created",
        "issue": {"number": 7, "pull_request": {"url": "..."}},
        "comment": {"body": "hey @trigger-handle please", "user": {"login": "alice"}},
        "repository": {"full_name": "a/b"},
        "sender": {"login": "alice"},
    }
    result = await fanout_event(
        bus,
        "issue_comment",
        "del-trigger-override",
        payload,
        operator_default_mention_login="deerflow-bot",
    )
    assert result["fired_agents"] == ["agent-x"], result


@pytest.mark.asyncio
async def test_operator_default_blank_string_treated_as_none(base_dir: Path) -> None:
    """An empty / whitespace-only operator default must not silently
    substitute itself as the mention handle.

    A misconfigured ``channels.github.default_mention_login: ""`` would
    otherwise yield ``require_mention`` gating on the empty string,
    which silently lets every mention through (or rejects everything,
    depending on how downstream logic treats it). Whitespace is stripped
    and falsy values fall through to the existing ``agent.name``
    fallback — preserving the pre-R8 contract for misconfigured installs.
    """
    bus = MessageBus()
    _write_agent(
        base_dir,
        "default",
        "assistant",
        {
            "name": "assistant",
            "github": {
                "bindings": [
                    {"repo": "a/b", "triggers": {"issue_comment": {"require_mention": True}}},
                ],
            },
        },
    )
    payload = {
        "action": "created",
        "issue": {"number": 7, "pull_request": {"url": "..."}},
        "comment": {"body": "hey @assistant please", "user": {"login": "alice"}},
        "repository": {"full_name": "a/b"},
        "sender": {"login": "alice"},
    }
    # Whitespace-only operator default → fall through to agent.name.
    result = await fanout_event(
        bus,
        "issue_comment",
        "del-blank-opdef",
        payload,
        operator_default_mention_login="   ",
    )
    assert result["fired_agents"] == ["assistant"], result


@pytest.mark.asyncio
async def test_bot_login_whitespace_only_treated_as_none(base_dir: Path) -> None:
    """A whitespace-only ``github.bot_login`` must not silently become the
    mention-gating handle.

    AGENTS.md documents the whole ``require_mention`` precedence chain
    (``trigger.mention_login`` -> ``github.bot_login`` ->
    ``channels.github.default_mention_login`` -> ``agent.name``) as treating
    whitespace-only defaults as unset. A misconfigured ``bot_login: "   "``
    (e.g. a YAML templating slip) is truthy in Python, so an unstripped
    ``github.bot_login or operator_default or agent.name`` never falls
    through to the working ``agent.name`` fallback — every legitimate
    ``@assistant`` mention is silently rejected and the trigger can never
    fire again until an operator notices and fixes the typo.
    """
    bus = MessageBus()
    _write_agent(
        base_dir,
        "default",
        "assistant",
        {
            "name": "assistant",
            "github": {
                "bot_login": "   ",  # whitespace-only — must be treated as unset
                "bindings": [
                    {"repo": "a/b", "triggers": {"issue_comment": {"require_mention": True}}},
                ],
            },
        },
    )
    payload = {
        "action": "created",
        "issue": {"number": 7, "pull_request": {"url": "..."}},
        "comment": {"body": "hey @assistant please", "user": {"login": "alice"}},
        "repository": {"full_name": "a/b"},
        "sender": {"login": "alice"},
    }
    # Whitespace-only bot_login → falls through to the agent.name fallback.
    result = await fanout_event(bus, "issue_comment", "del-blank-bot-login", payload)
    assert result["fired_agents"] == ["assistant"], result


@pytest.mark.asyncio
async def test_trigger_mention_login_whitespace_only_treated_as_none(base_dir: Path) -> None:
    """A whitespace-only per-trigger ``mention_login`` must not silently
    become the mention-gating handle either.

    Same contract as ``test_bot_login_whitespace_only_treated_as_none``, one
    link higher in the precedence chain: ``event_should_fire`` reads
    ``trigger.mention_login`` first. A misconfigured
    ``mention_login: "   "`` is truthy, so an unstripped
    ``trigger.mention_login or default_mention_login`` never falls through
    to the agent's real ``github.bot_login`` handle.
    """
    bus = MessageBus()
    _write_agent(
        base_dir,
        "default",
        "coder",
        {
            "name": "coder",
            "github": {
                "bot_login": "deerflow-bot",  # the real, working fallback handle
                "bindings": [
                    {
                        "repo": "a/b",
                        "triggers": {
                            "issue_comment": {
                                "require_mention": True,
                                "mention_login": "   ",  # whitespace-only — must be treated as unset
                            }
                        },
                    },
                ],
            },
        },
    )
    payload = {
        "action": "created",
        "issue": {"number": 7, "pull_request": {"url": "..."}},
        "comment": {"body": "hey @deerflow-bot please look", "user": {"login": "alice"}},
        "repository": {"full_name": "a/b"},
        "sender": {"login": "alice"},
    }
    # Whitespace-only trigger.mention_login → falls through to github.bot_login.
    result = await fanout_event(bus, "issue_comment", "del-blank-trigger-mention", payload)
    assert result["fired_agents"] == ["coder"], result


# ---------------------------------------------------------------------------
# Multiple agents
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multiple_agents_on_same_repo_event(base_dir: Path) -> None:
    bus = MessageBus()
    for n in ("alpha", "beta"):
        _write_agent(
            base_dir,
            "default",
            n,
            {
                "name": n,
                "github": {
                    "bindings": [
                        {"repo": "a/b", "triggers": {"pull_request": {}}},
                    ],
                },
            },
        )
    payload = {
        "action": "opened",
        "pull_request": {"number": 1, "user": {"login": "x"}},
        "repository": {"full_name": "a/b"},
        "sender": {"login": "x"},
    }
    result = await fanout_event(bus, "pull_request", "del-multi", payload)
    assert sorted(result["fired_agents"]) == ["alpha", "beta"]
    messages = await _drain(bus)
    assert sorted(m.metadata["agent_name"] for m in messages) == ["alpha", "beta"]


# ---------------------------------------------------------------------------
# Registry scan stays off the event loop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fanout_offloads_registry_scan_to_thread(base_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The registry rebuild must not block the asyncio event loop.

    A slow filesystem (NFS, container volume, large agent set) would
    otherwise push the webhook past GitHub's 10s delivery timeout. We
    offload via ``asyncio.to_thread``; verify by intercepting
    ``build_github_agent_registry`` and asserting it runs on a non-main
    thread.
    """
    import threading

    main_thread = threading.get_ident()
    seen_threads: list[int] = []

    from app.gateway.github import dispatcher as dispatcher_module

    real = dispatcher_module.build_github_agent_registry

    def _spy() -> dict:
        seen_threads.append(threading.get_ident())
        return real()

    monkeypatch.setattr(dispatcher_module, "build_github_agent_registry", _spy)

    _write_agent(
        base_dir,
        "default",
        "agent-x",
        {"name": "agent-x", "github": {"bindings": [{"repo": "a/b", "triggers": {"pull_request": {"actions": ["opened"]}}}]}},
    )
    payload = {
        "action": "opened",
        "pull_request": {"number": 1, "user": {"login": "u"}, "title": "x", "body": ""},
        "repository": {"full_name": "a/b"},
        "sender": {"login": "u"},
    }
    await fanout_event(MessageBus(), "pull_request", "del-thread", payload)

    assert seen_threads, "registry scan was not invoked"
    assert main_thread not in seen_threads, "registry scan must run off the event loop"


# ---------------------------------------------------------------------------
# Per-agent thread separation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_coder_and_reviewer_on_same_pr_get_distinct_threads(base_dir: Path) -> None:
    """Two agents bound to the same PR must NOT share a LangGraph thread.

    Headline guarantee of the per-agent thread design. If both agents
    landed on one thread:
        * ``multitask_strategy="reject"`` would silently drop one run
          on every dual-mention (``@coder @reviewer please ...``).
        * Their message histories and sandbox state would interleave.
        * Cancelling one would interrupt the other.

    Verify here that ``preferred_thread_id`` and ``topic_id`` both
    diverge between bindings on the same ``(repo, number)``. ``topic_id``
    is the ChannelStore key component, so the manager will look up a
    different cached thread per agent and pin each to its own deterministic
    UUID5 on first arrival.
    """
    bus = MessageBus()
    for n, login in (("coder", "coder-bot"), ("reviewer", "reviewer-bot")):
        _write_agent(
            base_dir,
            "default",
            n,
            {
                "name": n,
                "github": {
                    "bot_login": login,
                    "bindings": [
                        {
                            "repo": "a/b",
                            "triggers": {"pull_request": {"actions": ["opened"]}},
                        }
                    ],
                },
            },
        )
    payload = {
        "action": "opened",
        "pull_request": {"number": 7, "user": {"login": "alice"}, "title": "x", "body": ""},
        "repository": {"full_name": "a/b"},
        "sender": {"login": "alice"},
    }
    result = await fanout_event(bus, "pull_request", "del-split", payload)
    assert sorted(result["fired_agents"]) == ["coder", "reviewer"]

    messages = await _drain(bus)
    assert len(messages) == 2
    by_agent = {m.metadata["agent_name"]: m for m in messages}

    coder, reviewer = by_agent["coder"], by_agent["reviewer"]

    # Distinct LangGraph threads.
    assert coder.metadata["preferred_thread_id"] != reviewer.metadata["preferred_thread_id"]
    # Distinct store rows (manager keys on (channel_name, chat_id, topic_id)).
    assert coder.topic_id != reviewer.topic_id
    assert coder.topic_id == "7:coder"
    assert reviewer.topic_id == "7:reviewer"
    # Each metadata mirrors its own thread id.
    assert coder.metadata["preferred_thread_id"] == coder.metadata["github"]["thread_id"]
    assert reviewer.metadata["preferred_thread_id"] == reviewer.metadata["github"]["thread_id"]
