"""Tests for ``logging_level_from_config`` and ``apply_logging_level`` (``config.yaml`` ``log_level`` mapping)."""

import logging

import pytest

from deerflow.config.app_config import apply_logging_level, logging_level_from_config


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("debug", logging.DEBUG),
        ("INFO", logging.INFO),
        ("warning", logging.WARNING),
        ("error", logging.ERROR),
        ("critical", logging.CRITICAL),
        ("  Debug  ", logging.DEBUG),
        (None, logging.INFO),
        ("", logging.INFO),
    ],
)
def test_logging_level_from_config_known_and_defaults(name: str | None, expected: int) -> None:
    assert logging_level_from_config(name) == expected


def test_logging_level_from_config_unknown_falls_back_to_info() -> None:
    assert logging_level_from_config("not-a-real-level-name") == logging.INFO


class TestApplyLoggingLevel:
    """Tests for ``apply_logging_level`` — verifies deerflow/app logger and handler levels."""

    def setup_method(self) -> None:
        root = logging.root
        self._original_root_level = root.level
        self._original_root_handlers = list(root.handlers)
        self._original_handler_levels = {handler: handler.level for handler in self._original_root_handlers}
        self._original_deerflow_level = logging.getLogger("deerflow").level
        self._original_app_level = logging.getLogger("app").level

    def teardown_method(self) -> None:
        root = logging.root
        current_handlers = list(root.handlers)

        for handler in current_handlers:
            if handler not in self._original_root_handlers:
                root.removeHandler(handler)
                handler.close()

        for handler in list(root.handlers):
            root.removeHandler(handler)

        for handler in self._original_root_handlers:
            handler.setLevel(self._original_handler_levels[handler])
            root.addHandler(handler)

        root.setLevel(self._original_root_level)
        logging.getLogger("deerflow").setLevel(self._original_deerflow_level)
        logging.getLogger("app").setLevel(self._original_app_level)

    def test_sets_deerflow_app_logger_levels(self) -> None:
        apply_logging_level("debug")
        assert logging.getLogger("deerflow").level == logging.DEBUG
        assert logging.getLogger("app").level == logging.DEBUG

    def test_lowers_handler_level(self) -> None:
        handler = logging.StreamHandler()
        handler.setLevel(logging.WARNING)
        logging.root.addHandler(handler)
        apply_logging_level("debug")
        assert handler.level == logging.DEBUG

    def test_does_not_raise_handler_level(self) -> None:
        handler = logging.StreamHandler()
        handler.setLevel(logging.WARNING)
        logging.root.addHandler(handler)
        apply_logging_level("error")
        assert handler.level == logging.WARNING

    def test_does_not_modify_root_logger(self) -> None:
        logging.root.setLevel(logging.WARNING)
        apply_logging_level("debug")
        assert logging.root.level == logging.WARNING
        apply_logging_level("error")
        assert logging.root.level == logging.WARNING

    def test_defaults_to_info(self) -> None:
        apply_logging_level(None)
        assert logging.getLogger("deerflow").level == logging.INFO
        assert logging.getLogger("app").level == logging.INFO
