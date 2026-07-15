from __future__ import annotations

from dataclasses import dataclass

from billing.models import InvoiceLine
from billing.tax import calculate_tax_cents


@dataclass(frozen=True)
class Invoice:
    lines: list[InvoiceLine]
    subtotal_cents: int
    taxable_subtotal_cents: int
    tax_cents: int
    total_cents: int
    paid_cents: int
    refunded_cents: int
    balance_due_cents: int


def build_invoice(
    lines: list[InvoiceLine],
    *,
    tax_rate_bps: int,
    payments_cents: list[int] | None = None,
    refunds_cents: list[int] | None = None,
) -> Invoice:
    payments_cents = payments_cents or []
    refunds_cents = refunds_cents or []
    subtotal_cents = sum(line.net_cents() for line in lines)
    taxable_subtotal_cents = sum(line.net_cents() for line in lines)
    tax_cents = calculate_tax_cents(taxable_subtotal_cents, tax_rate_bps)
    total_cents = subtotal_cents + tax_cents
    paid_cents = sum(payments_cents)
    refunded_cents = sum(refunds_cents)
    balance_due_cents = total_cents - paid_cents
    return Invoice(
        lines=lines,
        subtotal_cents=subtotal_cents,
        taxable_subtotal_cents=taxable_subtotal_cents,
        tax_cents=tax_cents,
        total_cents=total_cents,
        paid_cents=paid_cents,
        refunded_cents=refunded_cents,
        balance_due_cents=balance_due_cents,
    )
