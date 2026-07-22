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


# ---------------------------------------------------------------------------
# Inbound dedupe identity — redelivery / replay protection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delivery_id_populates_inbound_dedupe_identity(base_dir: Path) -> None:
    """Each fanned-out message carries the identity ChannelManager dedupes on.

    The inbound dedupe added for the IM channels in PR #3584 keys on a
    top-level ``metadata["message_id"]`` plus a workspace id. The GitHub
    channel added later (PR #3754) never populated either, so a redelivered
    webhook (native "Redeliver" button, REST API, or an operator's own
    recovery script — GitHub does not auto-retry a failed delivery) re-ran
    the agent. Fan-out now stamps the ``X-GitHub-Delivery`` GUID (scoped per owning
    user + agent) as the message id and the repo as the workspace id,
    exactly where ``ChannelManager._inbound_dedupe_key`` looks.
    """
    bus = MessageBus()
    _write_agent(
        base_dir,
        "default",
        "reviewer",
        {"name": "reviewer", "github": {"installation_id": 1234, "bindings": [{"repo": "zhfeng/llm-gateway", "triggers": {"pull_request": {"actions": ["opened"]}}}]}},
    )
    payload = {
        "action": "opened",
        "pull_request": {"number": 7, "title": "x", "user": {"login": "zhfeng"}, "body": ""},
        "repository": {"full_name": "zhfeng/llm-gateway"},
        "sender": {"login": "zhfeng"},
    }
    await fanout_event(bus, "pull_request", "del-abc", payload)
    (msg,) = await _drain(bus)

    # Workspace id: the manager fails closed without one; repo is stable + unique.
    assert msg.workspace_id == "zhfeng/llm-gateway"
    # Stable per-(delivery, user, agent) message id the manager keys dedupe
    # on, read from the top level of metadata (not the nested ``github``
    # block). ``user_id`` here is "default" — the owning user this agent
    # config lives under.
    assert msg.metadata["message_id"] == "del-abc:default:reviewer"


@pytest.mark.asyncio
async def test_dedupe_identity_stable_across_redelivery_and_distinct_per_agent(base_dir: Path) -> None:
    """Redelivery reproduces the same ids (deduped); agents/deliveries differ.

    A single delivery fans out to N agents, so the dedupe id is scoped to
    (delivery, agent): replaying the same ``X-GitHub-Delivery`` yields identical
    ids per agent (the manager drops the replay) while two agents on one
    delivery — or a genuinely new delivery — keep distinct ids and still fire.
    """
    bus = MessageBus()
    for n in ("coder", "reviewer"):
        _write_agent(base_dir, "default", n, {"name": n, "github": {"bindings": [{"repo": "a/b", "triggers": {"pull_request": {"actions": ["opened"]}}}]}})
    payload = {
        "action": "opened",
        "pull_request": {"number": 1, "title": "x", "user": {"login": "u"}, "body": ""},
        "repository": {"full_name": "a/b"},
        "sender": {"login": "u"},
    }

    async def _ids(delivery: str) -> dict[str, str]:
        await fanout_event(bus, "pull_request", delivery, payload)
        return {m.metadata["agent_name"]: m.metadata["message_id"] for m in await _drain(bus)}

    first = await _ids("del-1")
    redelivery = await _ids("del-1")
    second = await _ids("del-2")

    # Per-agent within one delivery: distinct, so neither agent is dropped.
    assert first["coder"] != first["reviewer"]
    # Redelivery of the same GUID: identical per agent (manager will dedupe).
    assert redelivery == first
    # New delivery: every id changes, so both agents fire again.
    assert second["coder"] != first["coder"]
    assert second["reviewer"] != first["reviewer"]


@pytest.mark.asyncio
async def test_dedupe_identity_distinguishes_same_agent_name_across_users(base_dir: Path) -> None:
    """Two different users' same-named agents must not collide (willem-bd, PR #4104).

    ``ChannelManager._inbound_dedupe_key`` indexes on
    ``(channel, workspace_id, chat_id, message_id)``. For GitHub both
    ``workspace_id`` and ``chat_id`` are the repo, so ``owner_user_id`` was
    never represented anywhere in the key. Before folding ``match.user_id``
    into the per-message id, two users each binding an agent named
    ``reviewer`` to the same repo+event produced the *identical* id
    ``f"{delivery_id}:reviewer"`` for both fan-out messages, so
    ``ChannelManager._is_duplicate_inbound`` silently dropped the second
    user's run as a false-positive duplicate of the first — even though
    GitHub only delivered the webhook once and both users' agents matched.
    """
    bus = MessageBus()
    for user_id in ("alice", "bob"):
        _write_agent(
            base_dir,
            user_id,
            "reviewer",
            {
                "name": "reviewer",
                "github": {
                    "bindings": [
                        {"repo": "a/b", "triggers": {"pull_request": {"actions": ["opened"]}}},
                    ],
                },
            },
        )
    payload = {
        "action": "opened",
        "pull_request": {"number": 1, "title": "x", "user": {"login": "u"}, "body": ""},
        "repository": {"full_name": "a/b"},
        "sender": {"login": "u"},
    }
    result = await fanout_event(bus, "pull_request", "del-cross-user", payload)
    assert result["fired_agents"] == ["reviewer", "reviewer"]

    messages = await _drain(bus)
    assert len(messages) == 2
    by_owner = {m.owner_user_id: m for m in messages}
    assert set(by_owner) == {"alice", "bob"}

    # The dedupe id must differ even though the agent name is identical —
    # otherwise the two users' fan-out messages are indistinguishable to
    # the manager's dedupe.
    assert by_owner["alice"].metadata["message_id"] != by_owner["bob"].metadata["message_id"]

    # Prove the actual observable consequence, not just that the raw ids
    # differ: neither user's message is treated as a duplicate of the
    # other inside the same ChannelManager dedupe window.
    from app.channels.manager import ChannelManager
    from app.channels.store import ChannelStore

    manager = ChannelManager(bus=MessageBus(), store=ChannelStore(path=base_dir / "dedupe-store.json"))
    assert manager._is_duplicate_inbound(by_owner["alice"]) is False
    assert manager._is_duplicate_inbound(by_owner["bob"]) is False


@pytest.mark.asyncio
async def test_missing_delivery_header_leaves_dedupe_open(base_dir: Path) -> None:
    """Absent ``X-GitHub-Delivery`` fails open (no dedupe id), never collapses.

    ``delivery_id`` originates from an optional header and can be empty. An
    empty value must not become a constant key that would silently drop
    distinct deliveries — it yields no dedupe id, i.e. the pre-fix behavior.

    This asserts the actual manager-level consequence, not just the raw
    dispatcher-layer id: today ``_inbound_dedupe_key`` returns ``None`` for a
    falsy ``message_id``, so ``_is_duplicate_inbound`` returns ``False`` and
    never records a key. A future change that let a missing id fall through
    as a real (constant) key would silently collapse every header-less
    delivery into "the same" message; asserting on two separate header-less
    deliveries pins that neither is ever treated as a duplicate of the other
    (willem-bd, PR #4104 review).
    """
    from app.channels.manager import ChannelManager
    from app.channels.store import ChannelStore

    bus = MessageBus()
    _write_agent(base_dir, "default", "reviewer", {"name": "reviewer", "github": {"bindings": [{"repo": "a/b", "triggers": {"pull_request": {"actions": ["opened"]}}}]}})
    payload = {
        "action": "opened",
        "pull_request": {"number": 1, "title": "x", "user": {"login": "u"}, "body": ""},
        "repository": {"full_name": "a/b"},
        "sender": {"login": "u"},
    }
    manager = ChannelManager(bus=MessageBus(), store=ChannelStore(path=base_dir / "dedupe-store.json"))

    await fanout_event(bus, "pull_request", "", payload)
    (first,) = await _drain(bus)
    assert first.metadata["message_id"] is None
    assert manager._is_duplicate_inbound(first) is False

    await fanout_event(bus, "pull_request", "", payload)
    (second,) = await _drain(bus)
    assert second.metadata["message_id"] is None
    assert manager._is_duplicate_inbound(second) is False


# ---------------------------------------------------------------------------
# Redundant review-comment fan-out suppression (issue #4121, narrower slice)
#
# GitHub fires one `pull_request_review_comment` webhook per inline comment
# attached to a review submission, IN ADDITION to the single
# `pull_request_review` event for the review as a whole. A bot reviewer like
# CodeRabbit routinely leaves 20-30 inline comments per review, so this
# floods the webhook with near-duplicate deliveries that carry nothing the
# agent doesn't already have -- it fetches every inline comment itself (via
# `gh api`) when it processes the parent `pull_request_review` event. Each
# such companion comment carries `pull_request_review_id` and (unless it is
# itself a reply within an existing thread) no `in_reply_to_id`.
#
# PR #4131 review (willem-bd, zhfeng -- "Request changes"): the first cut of
# this filter suppressed every such companion comment unconditionally,
# before the registry lookup / per-agent loop even ran. That is only safe
# for a binding that ALSO subscribes to `pull_request_review` on the same
# repo -- it has its own path to the review content, via
# `_pr_review_prompt`, so the companion comment is genuinely redundant for
# it. A binding that subscribes to `pull_request_review_comment` ALONE
# never receives the parent review event at all (events are opt-in per
# binding, see `triggers.py`), so the parent event was never a substitute
# for it in the first place -- suppressing the companion comment too would
# silently drop the entire review submission's inline content for that
# binding, with no recovery path. The filter is now applied per matched
# binding: it only suppresses when that SAME binding also has its own
# `pull_request_review` trigger configured for this repo.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_review_comment_companion_to_review_is_suppressed(base_dir: Path) -> None:
    """A `pull_request_review_comment` that is pure fan-out from a parent
    `pull_request_review` submission is suppressed for a binding that is
    ALSO registered for `pull_request_review` on the same repo -- that
    binding has its own path to the review content, so the companion
    comment is genuinely redundant for it. This is the original bug fix's
    value and must be preserved by the binding-scoped gate.

    ``pull_request_review_id`` is set (this comment belongs to a review)
    and ``in_reply_to_id`` is absent (this is not a reply-to-a-reply), so
    this is the classic "CodeRabbit storm" companion event.
    """
    bus = MessageBus()
    _write_agent(
        base_dir,
        "default",
        "reviewer",
        {
            "name": "reviewer",
            "github": {
                "bindings": [
                    {
                        "repo": "a/b",
                        "triggers": {
                            # Dual-subscribed: this binding also listens for
                            # the parent review event, so it has its own
                            # path to the review's content.
                            "pull_request_review": {},
                            "pull_request_review_comment": {"require_mention": False},
                        },
                    }
                ],
            },
        },
    )
    payload = {
        "action": "created",
        "pull_request": {"number": 7},
        "comment": {
            "body": "nit: consider renaming this variable.",
            "user": {"login": "coderabbitai[bot]"},
            "pull_request_review_id": 999001,
            "in_reply_to_id": None,
        },
        "repository": {"full_name": "a/b"},
        "sender": {"login": "coderabbitai[bot]"},
    }
    result = await fanout_event(bus, "pull_request_review_comment", "del-storm-1", payload)
    # The binding-scoped gate runs inside the per-agent loop (after the
    # registry lookup), so the agent DOES show up as matched -- it just
    # doesn't fire. This is more informative than the old global early
    # return (which reported `matched_agents: []` even when an agent would
    # have matched -- PR #4131 review, zhfeng's "Minor" observability note).
    assert result["matched_agents"] == ["reviewer"], result
    assert result["fired_agents"] == [], result
    assert any(s["agent"] == "reviewer" and s["reason"] == "redundant_review_comment" for s in result["skipped"]), result
    assert await _drain(bus) == []


@pytest.mark.asyncio
async def test_review_comment_only_binding_not_suppressed(base_dir: Path) -> None:
    """Regression fix (PR #4131 review, Concern 1 -- zhfeng, "Request
    changes"): a binding registered for `pull_request_review_comment`
    ALONE (no `pull_request_review` trigger) must still fire on a
    companion comment, even though the payload has the exact same
    fan-out shape as the previous test.

    Such a binding never receives the parent `pull_request_review` event
    at all -- events are opt-in per binding (`triggers.py`) -- so the
    companion comment is its ONLY delivery of this review's inline
    content. Unconditionally suppressing it (the as-reviewed behavior)
    would be a silent, total loss of the review's inline comments for
    this binding, not noise reduction. This is the same operator config
    zhfeng's review used as the concrete failure scenario:
    `pull_request_review_comment: {require_mention: false}` with no
    `pull_request_review` binding, receiving a CodeRabbit-style inline
    comment.
    """
    bus = MessageBus()
    _write_agent(
        base_dir,
        "default",
        "reviewer",
        {
            "name": "reviewer",
            "github": {
                "bindings": [
                    {
                        "repo": "a/b",
                        # Single-subscribed: NO `pull_request_review` trigger.
                        "triggers": {"pull_request_review_comment": {"require_mention": False}},
                    }
                ],
            },
        },
    )
    payload = {
        "action": "created",
        "pull_request": {"number": 7},
        "comment": {
            "body": "nit: consider renaming this variable.",
            "user": {"login": "coderabbitai[bot]"},
            "pull_request_review_id": 999001,
            "in_reply_to_id": None,
        },
        "repository": {"full_name": "a/b"},
        "sender": {"login": "coderabbitai[bot]"},
    }
    result = await fanout_event(bus, "pull_request_review_comment", "del-storm-2", payload)
    assert result["matched_agents"] == ["reviewer"], result
    assert result["fired_agents"] == ["reviewer"], result
    assert result["skipped"] == [], result
    messages = await _drain(bus)
    assert len(messages) == 1
    assert messages[0].metadata["agent_name"] == "reviewer"


@pytest.mark.asyncio
async def test_review_comment_not_suppressed_when_review_trigger_is_on_different_repo(base_dir: Path) -> None:
    """The binding-scoped gate must key off the trigger on THIS repo, not
    merely "does this agent have a `pull_request_review` trigger anywhere".

    An agent can have multiple `github` bindings (one per repo). An agent
    that listens for `pull_request_review` on repo X and
    `pull_request_review_comment`-only on repo Y must still fire on Y's
    companion comments -- the review coverage on X is irrelevant to Y.
    """
    bus = MessageBus()
    _write_agent(
        base_dir,
        "default",
        "multi-repo-bot",
        {
            "name": "multi-repo-bot",
            "github": {
                "bindings": [
                    {
                        "repo": "owner/x",
                        "triggers": {"pull_request_review": {}},
                    },
                    {
                        "repo": "owner/y",
                        "triggers": {"pull_request_review_comment": {"require_mention": False}},
                    },
                ],
            },
        },
    )
    payload = {
        "action": "created",
        "pull_request": {"number": 3},
        "comment": {
            "body": "nit on repo Y.",
            "user": {"login": "coderabbitai[bot]"},
            "pull_request_review_id": 42,
            "in_reply_to_id": None,
        },
        "repository": {"full_name": "owner/y"},
        "sender": {"login": "coderabbitai[bot]"},
    }
    result = await fanout_event(bus, "pull_request_review_comment", "del-storm-3", payload)
    assert result["fired_agents"] == ["multi-repo-bot"], result
    assert result["skipped"] == [], result


@pytest.mark.asyncio
async def test_review_comment_reply_within_thread_still_fires(base_dir: Path) -> None:
    """A genuine reply within an existing review-comment thread is a
    distinct interaction, not fan-out noise -- it must still fire even
    though ``pull_request_review_id`` is set, because ``in_reply_to_id``
    marks it as a reply rather than a fresh review-companion comment.
    """
    bus = MessageBus()
    _write_agent(
        base_dir,
        "default",
        "reviewer",
        {
            "name": "reviewer",
            "github": {
                "bindings": [
                    {
                        "repo": "a/b",
                        "triggers": {"pull_request_review_comment": {"require_mention": False}},
                    }
                ],
            },
        },
    )
    payload = {
        "action": "created",
        "pull_request": {"number": 7},
        "comment": {
            "body": "Good catch, fixed in the latest push.",
            "user": {"login": "alice"},
            "pull_request_review_id": 999001,
            "in_reply_to_id": 555002,
        },
        "repository": {"full_name": "a/b"},
        "sender": {"login": "alice"},
    }
    result = await fanout_event(bus, "pull_request_review_comment", "del-reply-1", payload)
    assert result["fired_agents"] == ["reviewer"], result
    assert result["skipped"] == []
    messages = await _drain(bus)
    assert len(messages) == 1


@pytest.mark.asyncio
async def test_review_comment_without_review_id_still_fires(base_dir: Path) -> None:
    """A `pull_request_review_comment` with no `pull_request_review_id` at
    all is not part of any review fan-out and must still fire.

    (Every real GitHub `pull_request_review_comment` carries this field,
    but the filter must key off its actual presence rather than assume
    it, so a malformed/legacy payload is never silently swallowed.)
    """
    bus = MessageBus()
    _write_agent(
        base_dir,
        "default",
        "reviewer",
        {
            "name": "reviewer",
            "github": {
                "bindings": [
                    {
                        "repo": "a/b",
                        "triggers": {"pull_request_review_comment": {"require_mention": False}},
                    }
                ],
            },
        },
    )
    payload = {
        "action": "created",
        "pull_request": {"number": 7},
        "comment": {
            "body": "Standalone inline comment, no parent review.",
            "user": {"login": "alice"},
        },
        "repository": {"full_name": "a/b"},
        "sender": {"login": "alice"},
    }
    result = await fanout_event(bus, "pull_request_review_comment", "del-noreviewid-1", payload)
    assert result["fired_agents"] == ["reviewer"], result
    assert result["skipped"] == []


@pytest.mark.asyncio
async def test_issue_comment_unaffected_by_review_comment_filter(base_dir: Path) -> None:
    """A standalone top-level `issue_comment` must be completely unaffected
    by the review-comment redundancy filter -- it is a different event
    name entirely, so the filter must not touch it.
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
                    {
                        "repo": "a/b",
                        "triggers": {"issue_comment": {"require_mention": False}},
                    }
                ],
            },
        },
    )
    payload = {
        "action": "created",
        "issue": {"number": 3, "pull_request": {"url": "..."}},
        "comment": {"body": "just a regular comment", "user": {"login": "alice"}},
        "repository": {"full_name": "a/b"},
        "sender": {"login": "alice"},
    }
    result = await fanout_event(bus, "issue_comment", "del-issue-1", payload)
    assert result["fired_agents"] == ["assistant"], result
    assert result["skipped"] == []


# ---------------------------------------------------------------------------
# require_mention conditional-delivery gap (PR #4131 review, Medium + Minor
# findings, willem-bd -- second review round, against the per-binding gate
# above which already shipped in response to the FIRST round)
#
# The per-binding gate's premise is that a binding also registered for
# `pull_request_review` on this repo has an independent path to the review
# content, so its companion comments are genuinely redundant for it. That
# premise only holds if the review event is GUARANTEED to fire. If the
# binding's `pull_request_review` trigger itself has `require_mention:
# true`, the review event can be silently dropped by its own mention check
# against `review["body"]` (the review's top-level summary) -- a field
# this `pull_request_review_comment` payload never carries, so there is no
# way to verify from here whether that check would pass. A human
# `@mention` living only inside one inline comment (not the review
# summary) would then be lost twice over: the review is filtered
# (`no_mention`) *and* the one inline comment that actually carries the
# mention is dropped here as "redundant" -- the same silent-loss shape as
# the original bug, just via a narrower path. `dispatcher.py` now treats a
# mention-gated review trigger as NOT covering its companion comments.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_review_comment_not_suppressed_when_review_trigger_requires_mention(base_dir: Path) -> None:
    """Reproduces willem-bd's exact Medium-finding scenario: a dual-subscribed
    binding whose `pull_request_review` trigger has `require_mention: true`,
    and a review whose summary would carry no mention typed only inside one
    inline comment.

    Only the `pull_request_review_comment` half of the scenario can be
    exercised at this layer -- the two events are separate webhook
    deliveries -- but that is exactly where the bug lived: on the
    as-reviewed code, this binding's mere registration for
    `pull_request_review` was enough to mark it "covered" and suppress the
    companion, regardless of that trigger's own `require_mention`. Since the
    paired review event's delivery can't be verified from a comment
    payload, that was a silent loss. The fix lets this companion fire on
    its own terms instead.

    The companion's own `pull_request_review_comment` trigger ALSO requires
    a mention here (the strictest version of the scenario), and the mention
    is present only in the comment body -- proving the fix actually
    delivers the content, not just an incidental extra fire.
    """
    bus = MessageBus()
    _write_agent(
        base_dir,
        "default",
        "reviewer",
        {
            "name": "reviewer",
            "github": {
                "bindings": [
                    {
                        "repo": "a/b",
                        "triggers": {
                            # The gap: this trigger requiring a mention means
                            # the paired `pull_request_review` event is not a
                            # guaranteed delivery path for this binding.
                            "pull_request_review": {"require_mention": True},
                            "pull_request_review_comment": {"require_mention": True},
                        },
                    }
                ],
            },
        },
    )
    payload = {
        "action": "created",
        "pull_request": {"number": 7},
        "comment": {
            # The mention lives ONLY here -- the (separate, not modeled in
            # this payload) review summary has none.
            "body": "@reviewer this needs another look before merging.",
            "user": {"login": "alice"},
            "pull_request_review_id": 999001,
            "in_reply_to_id": None,
        },
        "repository": {"full_name": "a/b"},
        "sender": {"login": "alice"},
    }
    result = await fanout_event(bus, "pull_request_review_comment", "del-req-mention-1", payload)
    assert result["fired_agents"] == ["reviewer"], result
    assert result["skipped"] == [], result
    messages = await _drain(bus)
    assert len(messages) == 1
    assert messages[0].metadata["agent_name"] == "reviewer"
    assert "@reviewer this needs another look" in messages[0].text


@pytest.mark.asyncio
async def test_review_comment_gate_is_independent_per_agent_in_same_call(base_dir: Path) -> None:
    """Two bindings on the same repo/event, evaluated in the SAME
    `fanout_event` call: one dual-subscribed (genuinely covered ->
    suppressed) and one review-comment-only (not covered -> fires).
    Willem-bd's review flagged this combined case as untested -- the
    per-binding decision must be independent within a single call, not
    accidentally global or order-dependent.
    """
    bus = MessageBus()
    _write_agent(
        base_dir,
        "default",
        "coder",
        {
            "name": "coder",
            "github": {
                "bindings": [
                    {
                        "repo": "a/b",
                        "triggers": {
                            "pull_request_review": {},
                            "pull_request_review_comment": {"require_mention": False},
                        },
                    }
                ],
            },
        },
    )
    _write_agent(
        base_dir,
        "default",
        "notifier",
        {
            "name": "notifier",
            "github": {
                "bindings": [
                    {
                        "repo": "a/b",
                        "triggers": {"pull_request_review_comment": {"require_mention": False}},
                    }
                ],
            },
        },
    )
    payload = {
        "action": "created",
        "pull_request": {"number": 7},
        "comment": {
            "body": "nit: consider renaming this variable.",
            "user": {"login": "coderabbitai[bot]"},
            "pull_request_review_id": 999001,
            "in_reply_to_id": None,
        },
        "repository": {"full_name": "a/b"},
        "sender": {"login": "coderabbitai[bot]"},
    }
    result = await fanout_event(bus, "pull_request_review_comment", "del-multi-agent-1", payload)
    assert set(result["matched_agents"]) == {"coder", "notifier"}, result
    assert result["fired_agents"] == ["notifier"], result
    assert result["skipped"] == [{"agent": "coder", "reason": "redundant_review_comment"}], result
    messages = await _drain(bus)
    assert len(messages) == 1
    assert messages[0].metadata["agent_name"] == "notifier"


@pytest.mark.asyncio
async def test_review_comment_redundant_skip_prefers_own_trigger_reason_when_it_also_fails(base_dir: Path) -> None:
    """Minor finding (willem-bd): when a companion is suppressed as
    redundant AND would independently have failed its own trigger filter
    (e.g. its own `require_mention` isn't satisfied), the more specific
    reason is reported instead of the generic `redundant_review_comment` --
    useful for operator debugging even though the event is skipped either
    way.
    """
    bus = MessageBus()
    _write_agent(
        base_dir,
        "default",
        "reviewer",
        {
            "name": "reviewer",
            "github": {
                "bindings": [
                    {
                        "repo": "a/b",
                        "triggers": {
                            # Not mention-gated -- genuinely covered.
                            "pull_request_review": {},
                            # But THIS trigger requires a mention the
                            # comment body below doesn't have.
                            "pull_request_review_comment": {"require_mention": True},
                        },
                    }
                ],
            },
        },
    )
    payload = {
        "action": "created",
        "pull_request": {"number": 7},
        "comment": {
            "body": "nit: consider renaming this variable.",
            "user": {"login": "coderabbitai[bot]"},
            "pull_request_review_id": 999001,
            "in_reply_to_id": None,
        },
        "repository": {"full_name": "a/b"},
        "sender": {"login": "coderabbitai[bot]"},
    }
    result = await fanout_event(bus, "pull_request_review_comment", "del-precedence-1", payload)
    assert result["fired_agents"] == [], result
    assert len(result["skipped"]) == 1
    reason = result["skipped"][0]["reason"]
    assert reason != "redundant_review_comment", result
    assert "mention" in reason, result
