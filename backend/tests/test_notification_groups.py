"""The group predicate accepts only a recorded connected Feishu group."""

import pytest


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
