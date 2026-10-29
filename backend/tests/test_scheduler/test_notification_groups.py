"""The group predicate accepts only a recorded connected Feishu group."""

import pytest

from app.channels.notification_groups import notification_group_display_name


@pytest.mark.parametrize(
    "metadata,expected",
    [
        ({"notification_group_name": "Release team"}, "Release team"),
        ({"notification_group_name": "  发布  小组  "}, "发布 小组"),
        ({"notification_group_name": "名" * 300}, "名" * 256),
        ({}, None),
        ({"notification_group_name": 123}, None),
        ({"notification_group_name": "  "}, None),
        (None, None),
    ],
)
def test_group_binding_names_are_explicit_bounded_labels(metadata, expected):
    assert notification_group_display_name(metadata) == expected


@pytest.mark.parametrize(
    "overrides,expected",
    [
        ({}, True),
        ({"provider": "wecom"}, False),
        ({"status": "revoked"}, False),
        ({"workspace_id": None}, False),
        ({"workspace_id": ""}, False),
        ({"workspace_id": "  ", "metadata": {"chat_id": "  ", "chat_type": "group"}}, False),
        ({"workspace_id": "oc_other"}, False),
        ({"metadata": None}, False),
        ({"metadata": []}, False),
        ({"metadata": {"chat_id": "oc_group"}}, False),
        ({"metadata": {"chat_id": "oc_group", "chat_type": "p2p"}}, False),
        ({"metadata": {"chat_id": "", "chat_type": "group"}}, False),
        ({"metadata": {"chat_id": ["oc_group"], "chat_type": "group"}}, False),
    ],
)
def test_feishu_group_predicate(overrides, expected):
    from app.channels.notification_groups import is_feishu_notification_group

    value = {"provider": "feishu", "status": "connected", "workspace_id": "oc_group", "metadata": {"chat_id": "oc_group", "chat_type": "group"}, **overrides}
    assert is_feishu_notification_group(**value) is expected


@pytest.mark.parametrize(
    "overrides,app_id,expected",
    [
        ({}, None, "group-1"),
        ({}, "app-1", "group-1"),
        ({"metadata": {"chat_type": "group"}}, "app-1", "group-1"),
        ({}, "app-2", None),
        ({"provider": "feishu"}, None, None),
        ({"status": "revoked"}, None, None),
        ({"workspace_id": "app-1:c2c"}, None, None),
        ({"workspace_id": ":group:group-1"}, None, None),
        ({"workspace_id": "app-1:group:"}, None, None),
        ({"workspace_id": " app-1:group:group-1"}, None, None),
        ({"metadata": {"chat_type": "c2c", "group_openid": "group-1"}}, None, None),
        ({"metadata": {"chat_type": "group", "group_openid": "other"}}, None, None),
    ],
)
def test_qq_group_predicate(overrides, app_id, expected):
    from app.channels.notification_groups import is_notification_group, qq_notification_group_openid

    value = {
        "provider": "qq",
        "status": "connected",
        "workspace_id": "app-1:group:group-1",
        "metadata": {"chat_type": "group", "group_openid": "group-1"},
        **overrides,
    }
    assert qq_notification_group_openid(**value, app_id=app_id) == expected
    if app_id is None:
        assert is_notification_group(**value) is (expected is not None)


@pytest.mark.parametrize(
    "overrides,bot_id,expected",
    [
        ({}, None, "wr_chat_1"),
        ({}, "bot-1", "wr_chat_1"),
        ({"workspace_id": "group:wr_chat_1", "metadata": {"aibotid": None, "chattype": "group", "chatid": "wr_chat_1"}}, None, "wr_chat_1"),
        ({}, "bot-2", None),
        ({"provider": "wechat"}, None, None),
        ({"status": "revoked"}, None, None),
        ({"workspace_id": "bot-1"}, None, None),
        ({"workspace_id": "bot-1:group:other"}, None, None),
        ({"metadata": {"aibotid": "bot-1", "chattype": "single", "chatid": "wr_chat_1"}}, None, None),
        ({"metadata": {"aibotid": "bot-1", "chattype": "group", "chatid": ""}}, None, None),
        ({"metadata": {"aibotid": "bot-1", "chattype": "group", "chatid": " wr_chat_1 "}}, None, None),
    ],
)
def test_wecom_group_predicate(overrides, bot_id, expected):
    from app.channels.notification_groups import is_notification_group, wecom_notification_group_chat_id

    value = {
        "provider": "wecom",
        "status": "connected",
        "workspace_id": "bot-1:group:wr_chat_1",
        "metadata": {"aibotid": "bot-1", "chattype": "group", "chatid": "wr_chat_1"},
        **overrides,
    }
    assert wecom_notification_group_chat_id(**value, bot_id=bot_id) == expected
    if bot_id is None:
        assert is_notification_group(**value) is (expected is not None)
