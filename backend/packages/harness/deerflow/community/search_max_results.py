"""Single owner for the bundled web-search providers' ``max_results`` knob.

Four providers (``ddg_search``, ``image_search``, ``fastcrw``, ``firecrawl``)
carried byte-identical copies of this coercion, differing only in the provider
label of their warning line. #5865 audited the family value by value against
the #5852 bar; folding the identical copies into one function is what lets the
remaining providers be brought onto the same bar one at a time without
re-deciding in each file what "invalid" means.

Deliberately *not* decided here: whether an otherwise-valid value has an upper
bound. That still differs per provider (six of them clamp, five pass the
configured number straight to the API), and narrowing or widening it is a
default-behavior change that needs a maintainer call, not a side effect of a
de-duplication.

``logger`` is a parameter rather than a module-level logger here on purpose:
callers pass their own logger so a warning keeps its originating module in
``record.name`` (``tests/test_ddg_search_tools.py`` pins that).
"""

from __future__ import annotations

import logging

DEFAULT_MAX_RESULTS = 5


def coerce_max_results(
    value: object,
    *,
    provider: str,
    logger: logging.Logger,
    default: int = DEFAULT_MAX_RESULTS,
) -> int:
    """Normalize a configured or parameter ``max_results`` into a positive int.

    Booleans and non-integral floats are rejected rather than coerced: ``bool``
    is an ``int`` subclass, so a bare ``int(value)`` turns ``true`` into ``1``,
    and ``int(3.5)`` silently truncates a YAML value the operator wrote wrong.
    An out-of-range float such as an unquoted ``max_results: .inf`` makes
    ``int()`` raise ``OverflowError``, which is caught here so the tool call
    falls back to the documented default instead of failing outright.

    Integral floats such as ``4.0`` stay valid, and no upper bound is applied.
    """
    if isinstance(value, bool) or (isinstance(value, float) and not value.is_integer()):
        count = 0
    else:
        try:
            count = int(value)  # type: ignore[call-overload]
        except (TypeError, ValueError, OverflowError):
            count = 0
    if count <= 0:
        logger.warning("Invalid %s max_results=%r; using default %s", provider, value, default)
        return default
    return count
