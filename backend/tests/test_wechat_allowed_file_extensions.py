"""The WeChat file-extension allowlist is only ever narrowed by entries it can read."""

from __future__ import annotations

import logging

from app.channels.message_bus import MessageBus
from app.channels.wechat import WechatChannel

_CONFIG = {"bot_token": "test-token"}
_DEFAULTS = WechatChannel.DEFAULT_ALLOWED_FILE_EXTENSIONS


def _channel(extensions=None) -> WechatChannel:
    config = dict(_CONFIG)
    if extensions is not None:
        config["allowed_file_extensions"] = extensions
    return WechatChannel(bus=MessageBus(), config=config)


def _warning_messages(caplog) -> list[str]:
    return [record.getMessage() for record in caplog.records if record.levelno >= logging.WARNING]


def test_absent_allowed_file_extensions_uses_the_built_in_defaults():
    channel = _channel()

    assert len(_DEFAULTS) > 1
    assert channel._allowed_file_extensions == set(_DEFAULTS)


def test_documented_list_narrows_the_allowlist():
    channel = _channel([".pdf", ".zip"])

    assert channel._allowed_file_extensions == {".pdf", ".zip"}
    assert channel._is_allowed_file_type("report.pdf", "application/pdf")
    assert not channel._is_allowed_file_type("notes.txt", "text/plain")


def test_dotless_and_padded_extension_names_are_normalized():
    channel = _channel(["pdf", " .DOC "])

    assert channel._allowed_file_extensions == {".pdf", ".doc"}


def test_scalar_extension_config_narrows_the_allowlist(caplog):
    """A single extension may be configured as a bare string, like its sibling host allowlist.

    ``allowed_file_extensions: .pdf`` is a restriction, so it must never widen
    back to the built-in defaults; only the named extension is admitted.
    """
    caplog.set_level(logging.WARNING, logger="app.channels.wechat")
    channel = _channel(".pdf")

    assert channel._allowed_file_extensions == {".pdf"}
    assert not channel._is_allowed_file_type("archive.zip", "application/zip")
    assert _warning_messages(caplog) == []


def test_scalar_extension_config_with_separators_warns(caplog):
    """A comma-separated scalar is one literal entry, and that must be visible at startup.

    ``allowed_file_extensions: ".pdf, .zip"`` reads like a list but yields the
    single bogus member ``{".pdf, .zip"}``, which matches no suffix and so blocks
    every file. The value stays fail-closed; ``_parse_allowed_users`` logs the
    same shape instead of leaving the operator to infer it from per-file warnings.
    """
    caplog.set_level(logging.WARNING, logger="app.channels.wechat")
    channel = _channel(".pdf, .zip")

    assert channel._allowed_file_extensions == {".pdf, .zip"}
    assert not channel._is_allowed_file_type("report.pdf", "application/pdf")
    assert any("scalar string containing separators" in message for message in _warning_messages(caplog))


def test_space_separated_scalar_extension_config_warns(caplog):
    caplog.set_level(logging.WARNING, logger="app.channels.wechat")
    channel = _channel(".pdf .zip")

    assert channel._allowed_file_extensions == {".pdf .zip"}
    assert any("scalar string containing separators" in message for message in _warning_messages(caplog))


def test_unreadable_extension_entry_is_skipped_and_logged(caplog):
    """A non-string entry must not become a bogus member such as ``.123``."""
    caplog.set_level(logging.WARNING, logger="app.channels.wechat")
    channel = _channel(["pdf", 123])

    assert channel._allowed_file_extensions == {".pdf"}
    assert any("allowed_file_extensions" in message and "123" in message for message in _warning_messages(caplog))


def test_extension_config_of_the_wrong_type_is_logged_before_falling_back(caplog):
    caplog.set_level(logging.WARNING, logger="app.channels.wechat")
    channel = _channel(123)

    assert channel._allowed_file_extensions == set(_DEFAULTS)
    assert any("allowed_file_extensions" in message for message in _warning_messages(caplog))


def test_empty_extension_config_stays_restricted(caplog):
    """An empty config value must not read as "no filter" at the gate."""
    caplog.set_level(logging.WARNING, logger="app.channels.wechat")
    channel = _channel([])

    assert channel._allowed_file_extensions == set(_DEFAULTS)
    assert not channel._is_allowed_file_type("setup.exe", "application/x-msdownload")
