"""Tests for JoinedGroupsScanner — list groups the account currently is in."""

from types import SimpleNamespace

import pytest

from tg_intel_crawler.collector.joined_scanner import (
    JoinedGroup,
    JoinedGroupsScanner,
)


class _FakeClient:
    """Minimal Telethon-like client that yields a fixed dialog list."""

    def __init__(self, dialogs):
        self._dialogs = dialogs

    def iter_dialogs(self):
        async def _gen():
            for d in self._dialogs:
                yield d

        return _gen()


def _dlg(
    *,
    title: str,
    chat_id: int = 1,
    username: str | None = None,
    is_user: bool = False,
    is_group: bool = False,
    is_channel: bool = False,
    broadcast: bool = False,
    megagroup: bool = False,
    bot: bool = False,
    participants_count: int | None = None,
):
    """Build a fake Telethon Dialog with the entity attrs the scanner reads."""
    entity = SimpleNamespace(
        id=chat_id,
        title=title,
        username=username,
        broadcast=broadcast,
        megagroup=megagroup,
        bot=bot,
        participants_count=participants_count,
    )
    return SimpleNamespace(
        is_user=is_user,
        is_group=is_group,
        is_channel=is_channel,
        entity=entity,
        title=title,
        name=title,
    )


@pytest.mark.asyncio
async def test_lists_groups_and_channels():
    client = _FakeClient([
        _dlg(title="A_grp", chat_id=1, username="agrp", is_group=True, megagroup=True),
        _dlg(title="A_chan", chat_id=2, username="achan", is_channel=True, broadcast=True),
        _dlg(title="Friend", chat_id=3, is_user=True),
    ])
    scanner = JoinedGroupsScanner(client)
    joined = await scanner.list_joined()

    assert {g.username for g in joined} == {"agrp", "achan"}
    types = {g.username: g.type for g in joined}
    assert types["agrp"] in ("group", "supergroup")
    assert types["achan"] == "channel"


@pytest.mark.asyncio
async def test_excludes_bots_and_users():
    client = _FakeClient([
        _dlg(title="ABot", chat_id=10, username="abot", is_user=True, bot=True),
        _dlg(title="Person", chat_id=11, is_user=True),
        _dlg(title="Real grp", chat_id=12, username="real", is_group=True, megagroup=True),
    ])
    joined = await JoinedGroupsScanner(client).list_joined()
    assert {g.username for g in joined} == {"real"}


@pytest.mark.asyncio
async def test_include_channels_false_filters_broadcast():
    client = _FakeClient([
        _dlg(title="Chan", chat_id=1, username="c1", is_channel=True, broadcast=True),
        _dlg(title="Grp", chat_id=2, username="g1", is_group=True, megagroup=True),
    ])
    joined = await JoinedGroupsScanner(client).list_joined(include_channels=False)
    assert {g.username for g in joined} == {"g1"}


@pytest.mark.asyncio
async def test_exclude_by_username():
    client = _FakeClient([
        _dlg(title="A", chat_id=1, username="keep", is_group=True, megagroup=True),
        _dlg(title="B", chat_id=2, username="drop", is_group=True, megagroup=True),
    ])
    joined = await JoinedGroupsScanner(client).list_joined(
        exclude_usernames={"drop"}
    )
    assert [g.username for g in joined] == ["keep"]


@pytest.mark.asyncio
async def test_exclude_by_chat_id():
    client = _FakeClient([
        _dlg(title="A", chat_id=11, username="a", is_group=True, megagroup=True),
        _dlg(title="B", chat_id=22, username="b", is_group=True, megagroup=True),
    ])
    joined = await JoinedGroupsScanner(client).list_joined(exclude_chat_ids={22})
    assert [g.username for g in joined] == ["a"]


@pytest.mark.asyncio
async def test_private_group_without_username_returns_chat_id_link():
    """Private megagroups have no username — link should fall back to chat_id."""
    client = _FakeClient([
        _dlg(title="Private", chat_id=999, username=None, is_group=True, megagroup=True),
    ])
    joined = await JoinedGroupsScanner(client).list_joined()
    assert len(joined) == 1
    assert joined[0].username is None
    assert joined[0].link == 999


@pytest.mark.asyncio
async def test_private_group_link_is_telethon_resolvable():
    """Telethon's client.get_entity / events.NewMessage can NOT resolve
    'https://t.me/c/<id>' URLs (those are web-client internal). For private
    groups the scanner must produce something Telethon can resolve directly:
    the integer chat_id."""
    client = _FakeClient([
        _dlg(title="P", chat_id=2572577780, username=None, is_group=True, megagroup=True),
    ])
    joined = await JoinedGroupsScanner(client).list_joined()
    assert len(joined) == 1
    # Link must be the int chat_id (or its str form), NOT the t.me/c/... URL
    # which Telethon rejects with "Cannot find any entity corresponding to ...".
    assert joined[0].link == 2572577780


@pytest.mark.asyncio
async def test_returns_joined_group_dataclass_with_metadata():
    client = _FakeClient([
        _dlg(
            title="X", chat_id=42, username="xgrp",
            is_group=True, megagroup=True, participants_count=1234,
        ),
    ])
    joined = await JoinedGroupsScanner(client).list_joined()
    assert len(joined) == 1
    g = joined[0]
    assert isinstance(g, JoinedGroup)
    assert g.title == "X"
    assert g.chat_id == 42
    assert g.members_count == 1234
    assert g.link == "https://t.me/xgrp"
