from __future__ import annotations

import logging

from app.gateway.app import _SecretRedactionFilter, _redact_log_value


def test_redact_log_value_masks_telegram_bot_tokens() -> None:
    assert _redact_log_value("bot123456:ABCdef_123") == "bot<redacted>"
    assert _redact_log_value("no secret here") == "no secret here"


def test_secret_redaction_filter_masks_record_message_and_args() -> None:
    record = logging.LogRecord(
        name="telegram.ext",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="token=%s bot123456:ABCdef_123",
        args=("bot123456:ABCdef_123",),
        exc_info=None,
        func=None,
    )

    flt = _SecretRedactionFilter()
    assert flt.filter(record) is True
    assert record.msg == "token=%s bot<redacted>"
    assert record.args == ("bot<redacted>",)

