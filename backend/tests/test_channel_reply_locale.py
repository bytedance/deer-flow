"""Language of DeerFlow's own IM replies (``app/channels/reply_locale.py``)."""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.channels import goal_status
from app.channels.reply_locale import CONNECT_REPLY_TEXT, ReplyLocaleResolver, connect_reply_text, resolve_reply_locale
from app.scheduler.notification_text import NOTIFICATION_LOCALES
from deerflow.persistence.base import Base
from deerflow.persistence.user.model import UserRow
from deerflow.persistence.user.preferences import UserPreferencesRepository


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def sessions(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/preferences.db")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        session.add(UserRow(id="alice", email="alice@example.com"))
        await session.commit()
    yield factory
    await engine.dispose()


@pytest.mark.anyio
@pytest.mark.parametrize("stored", ["zh-CN", "en-US"])
async def test_owner_preference_wins_over_the_configured_default(sessions, stored):
    await UserPreferencesRepository(sessions).patch("alice", {"locale": stored})
    other = "en-US" if stored == "zh-CN" else "zh-CN"
    assert await resolve_reply_locale("alice", session_factory=sessions, default_locale=other) == stored


@pytest.mark.anyio
@pytest.mark.parametrize("stored", ["fr-FR", "zh", 7, None])
async def test_unsupported_preference_uses_the_configured_default(sessions, stored):
    await UserPreferencesRepository(sessions).patch("alice", {"locale": stored})
    assert await resolve_reply_locale("alice", session_factory=sessions, default_locale="zh-CN") == "zh-CN"


@pytest.mark.anyio
async def test_missing_preference_uses_the_configured_default(sessions):
    await UserPreferencesRepository(sessions).patch("alice", {"model_name": "model-a"})
    assert await resolve_reply_locale("alice", session_factory=sessions, default_locale="zh-CN") == "zh-CN"
    assert await resolve_reply_locale("bob", session_factory=sessions, default_locale="zh-CN") == "zh-CN"


@pytest.mark.anyio
async def test_read_error_falls_back_and_logs(sessions, caplog):
    # An undecodable stored value makes the repository raise on read.
    async with sessions() as session:
        await session.execute(text("INSERT INTO user_preferences (user_id, key, value) VALUES ('alice', 'locale', 'not json {')"))
        await session.commit()
    with caplog.at_level(logging.WARNING, logger="app.channels.reply_locale"):
        assert await resolve_reply_locale("alice", session_factory=sessions, default_locale="zh-CN") == "zh-CN"
    assert "language preference" in caplog.text


@pytest.mark.anyio
async def test_no_owner_or_database_skips_the_read(monkeypatch):
    class _Unreachable:
        def __init__(self, sessions):
            raise AssertionError("the preference store must not be read")

    monkeypatch.setattr("app.channels.reply_locale.UserPreferencesRepository", _Unreachable)
    assert await resolve_reply_locale(None, session_factory=object(), default_locale="zh-CN") == "zh-CN"
    assert await resolve_reply_locale("alice", session_factory=None, default_locale="zh-CN") == "zh-CN"
    # An unsupported configured default ends at en-US.
    assert await resolve_reply_locale(None, session_factory=None, default_locale="fr-FR") == "en-US"
    assert await ReplyLocaleResolver().locale_for("alice") == "en-US"


_PROVIDERS = ("buzz", "dingtalk", "discord", "feishu", "qq", "slack", "telegram", "wechat", "wecom")
_ENGLISH_NAMES = {"buzz": "Buzz", "dingtalk": "DingTalk", "discord": "Discord", "feishu": "Feishu", "qq": "QQ", "slack": "Slack", "telegram": "Telegram", "wechat": "WeChat", "wecom": "WeCom"}


@pytest.mark.parametrize("provider", _PROVIDERS)
def test_english_connect_replies_are_unchanged(provider):
    name = _ENGLISH_NAMES[provider]
    assert connect_reply_text("connected", provider=provider, locale="en-US") == f"{name} connected to DeerFlow."
    assert connect_reply_text("invalid_code", provider=provider, locale="en-US") == f"{name} connection code is invalid or expired."
    assert connect_reply_text("incomplete", provider=provider, locale="en-US") == f"{name} connection could not be completed from this message."
    assert connect_reply_text("invalid_link", provider="telegram", locale="en-US") == "Telegram connection link is invalid or expired."
    assert connect_reply_text("private_chat_only", provider="wechat", locale="en-US") == "Please send the connection code in a private chat with the bot."


def test_chinese_connect_replies_space_latin_names_only():
    assert connect_reply_text("connected", provider="feishu", locale="zh-CN") == "飞书已连接到 DeerFlow。"
    assert connect_reply_text("connected", provider="slack", locale="zh-CN") == "Slack 已连接到 DeerFlow。"
    assert connect_reply_text("invalid_code", provider="wecom", locale="zh-CN") == "企业微信绑定码无效或已过期。"
    assert connect_reply_text("invalid_code", provider="qq", locale="zh-CN") == "QQ 绑定码无效或已过期。"
    assert connect_reply_text("incomplete", provider="dingtalk", locale="zh-CN") == "无法通过这条消息完成钉钉绑定。"
    assert connect_reply_text("incomplete", provider="discord", locale="zh-CN") == "无法通过这条消息完成 Discord 绑定。"
    assert connect_reply_text("invalid_link", provider="telegram", locale="zh-CN") == "Telegram 绑定链接无效或已过期。"
    assert connect_reply_text("private_chat_only", provider="wechat", locale="zh-CN") == "请在与机器人的私聊中发送绑定码。"


@pytest.mark.parametrize("table", [CONNECT_REPLY_TEXT, goal_status._TEXT], ids=["connect", "goal"])
def test_reply_tables_have_the_same_keys_in_every_language(table):
    assert set(table) == set(NOTIFICATION_LOCALES)
    for locale in NOTIFICATION_LOCALES:
        assert set(table[locale]) == set(table["en-US"])


@pytest.mark.anyio
async def test_channel_service_gives_its_manager_and_channels_one_resolver(monkeypatch, tmp_path):
    from app.channels import service as channel_service
    from app.channels.service import ChannelService
    from app.channels.store import JsonChannelStore
    from deerflow import reflection

    started_configs = []

    class _RecordingChannel:
        def __init__(self, *, bus, config):
            started_configs.append(config)
            self.is_running = False

        async def start(self):
            self.is_running = True

        async def stop(self):
            self.is_running = False

    repo = SimpleNamespace(session_factory=object())
    app_config = SimpleNamespace(channel_connections=SimpleNamespace(notification_locale="zh-CN"))
    service = ChannelService(channels_config={"fake": {"enabled": True}}, connection_repo=repo, app_config=app_config, store=JsonChannelStore(path=tmp_path / "store.json"))
    service._running = True
    monkeypatch.setitem(channel_service._CHANNEL_REGISTRY, "fake", "tests.fake:FakeChannel")
    monkeypatch.setattr(reflection, "resolve_class", lambda *_args, **_kwargs: _RecordingChannel)

    assert await service._start_channel("fake", {"enabled": True}) is True
    resolver = started_configs[0]["reply_locale"]
    assert resolver is service.manager._reply_locale
    assert resolver.default_locale == "zh-CN"
    assert resolver.session_factory is repo.session_factory

    # Without channel connections configured, replies default to en-US.
    assert ChannelService(channels_config={}, store=JsonChannelStore(path=tmp_path / "other.json")).manager._reply_locale == ReplyLocaleResolver()
