from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class InvoiceLine:
    sku: str
    unit_price_cents: int
    quantity: int
    discount_cents: int = 0
    taxable: bool = True

    def net_cents(self) -> int:
        gross = self.unit_price_cents * self.quantity
        return gross
