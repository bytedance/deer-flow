"""Malformed model pricing must not take the console reports down.

``_build_pricing_map`` reads ``models[*].pricing`` from config.yaml. A price that
is not a finite number has to be ignored: the value flows into every cost on
``/usage``, ``/stats`` and ``/runs``, and a non-finite one ends up in the JSON
body where Starlette rejects it (``allow_nan=False``).

Two shapes reach that state and only one used to be caught:

- ``nan`` / ``.inf`` convert successfully, so a plain ``float()`` returns them;
- ``10**400`` parses as an exact ``int`` (a JSON integer is not bounded by the
  float range) and ``float()`` raises ``OverflowError``.

The second is the same failure mode the counter path removed in #7736; this pins
it for pricing.
"""

from __future__ import annotations

import logging
import math
from types import SimpleNamespace

import pytest

from app.gateway.routers import console

CONFIG = {"input_per_million": 8, "output_per_million": 32, "currency": "CNY"}


def _pricing_map(monkeypatch, pricing: dict[str, object]) -> dict:
    models = [SimpleNamespace(name="m1", model="M1", pricing=pricing)]
    monkeypatch.setattr(console, "get_app_config", lambda: SimpleNamespace(models=models))
    return console._build_pricing_map()


def test_finite_pricing_is_kept(monkeypatch):
    """Control: an ordinary price map still reports both lookup keys."""
    pricing_map = _pricing_map(monkeypatch, CONFIG)

    assert set(pricing_map) == {"m1", "M1"}
    assert pricing_map["m1"].input_per_million == 8
    assert pricing_map["m1"].output_per_million == 32


@pytest.mark.parametrize(
    "bad_price",
    [10**400, -(10**400)],
    ids=["huge-int", "huge-negative-int"],
)
def test_integer_beyond_the_float_range_is_ignored(monkeypatch, bad_price):
    """float() raises OverflowError; the model is unpriced, not a 500."""
    pricing_map = _pricing_map(monkeypatch, {**CONFIG, "input_per_million": bad_price})

    assert pricing_map == {}


def test_cache_hit_price_beyond_the_float_range_is_ignored(monkeypatch):
    pricing_map = _pricing_map(
        monkeypatch,
        {**CONFIG, "input_cache_hit_per_million": 10**400},
    )

    assert pricing_map == {}


@pytest.mark.parametrize("bad_price", [True, False])
def test_boolean_price_is_ignored(monkeypatch, bad_price):
    """float(True) is 1.0: a boolean would silently bill one unit per million.

    ``_token_count`` rejects booleans for the same reason, so the two coercers
    agree on what counts as a number.
    """
    assert _pricing_map(monkeypatch, {**CONFIG, "input_cache_hit_per_million": bad_price}) == {}


def test_boolean_input_price_is_ignored(monkeypatch):
    """``True`` survives the ``or 0`` default, so it has to be rejected here."""
    assert _pricing_map(monkeypatch, {**CONFIG, "input_per_million": True}) == {}


@pytest.mark.parametrize("bad_price", [float("inf"), float("-inf"), float("nan")])
def test_non_finite_price_is_ignored(monkeypatch, bad_price):
    """Pinned: the guard #7736 added for non-finite floats stays in force."""
    assert _pricing_map(monkeypatch, {**CONFIG, "output_per_million": bad_price}) == {}


@pytest.mark.parametrize("bad_price", ["abc", "8usd", [1], {"x": 1}])
def test_unparsable_price_is_ignored(monkeypatch, bad_price):
    """Truthy values float() refuses; falsy ones were already read as 0."""
    assert _pricing_map(monkeypatch, {**CONFIG, "input_per_million": bad_price}) == {}


def test_large_but_finite_price_stays_usable(monkeypatch):
    """The fix must reject only what cannot be a float, not every big number."""
    pricing_map = _pricing_map(monkeypatch, {**CONFIG, "input_per_million": 10**30})

    assert pricing_map["m1"].input_per_million == pytest.approx(1e30)
    assert math.isfinite(pricing_map["m1"].input_per_million)


def test_missing_optional_cache_hit_price_keeps_the_model_priced(monkeypatch):
    """An absent hit price means "bill hits at the input price", not "malformed"."""
    pricing_map = _pricing_map(monkeypatch, CONFIG)

    assert pricing_map["m1"].input_cache_hit_per_million is None


def test_unusable_prices_keep_their_own_log_signatures(monkeypatch, caplog):
    """Warn once per model, naming the shape that failed.

    The two messages existed before the reconciliation (#7736 added
    "non-finite", the older path said "malformed"); collapsing them into one
    would silently break log greps, so each leg keeps its own text.
    """
    with caplog.at_level(logging.WARNING, logger=console.__name__):
        _pricing_map(monkeypatch, {**CONFIG, "output_per_million": float("inf")})
        _pricing_map(monkeypatch, {**CONFIG, "output_per_million": 10**400})

    messages = [record.getMessage() for record in caplog.records]
    assert any("ignoring non-finite pricing on model m1" in message for message in messages)
    assert any("ignoring malformed pricing on model m1" in message for message in messages)
