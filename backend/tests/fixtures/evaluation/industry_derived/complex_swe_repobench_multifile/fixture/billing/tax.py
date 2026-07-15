from __future__ import annotations


def calculate_tax_cents(amount_cents: int, rate_bps: int) -> int:
    """Return tax for an amount using basis points."""

    return int(amount_cents * rate_bps / 10_000)
