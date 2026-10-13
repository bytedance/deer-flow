"""Direct tests for the shared boolean-rejection helper."""

from typing import cast

import pytest
from pydantic import ValidationInfo

from deerflow.config._boolean_guards import reject_boolean


class _Probe:
    """Minimal harness so ``info.field_name`` resolves like a real field."""

    def __init__(self, field_name: str) -> None:
        self.field_name = field_name


def _info(field_name: str) -> ValidationInfo:
    return cast(ValidationInfo, _Probe(field_name))


def test_reject_boolean_names_the_field() -> None:
    with pytest.raises(ValueError, match="recursion_limit must be an integer, not a boolean"):
        reject_boolean(True, _info("recursion_limit"), kind="an integer")


def test_reject_boolean_passes_numbers_through() -> None:
    assert reject_boolean(0, _info("hard_limit"), kind="an integer") == 0
    assert reject_boolean(2.5, _info("interval"), kind="a number") == 2.5


def test_reject_boolean_custom_kind_wording() -> None:
    with pytest.raises(ValueError, match="command_timeout must be a number of seconds or null, not a boolean"):
        reject_boolean(True, _info("command_timeout"), kind="a number of seconds or null")
