from __future__ import annotations

from billing.invoice import Invoice


def summarize_invoice(invoice: Invoice) -> dict[str, int | str]:
    if invoice.balance_due_cents == 0:
        status = "paid"
    elif invoice.paid_cents == 0:
        status = "open"
    else:
        status = "partial"
    return {
        "status": status,
        "subtotal_cents": invoice.subtotal_cents,
        "tax_cents": invoice.tax_cents,
        "total_cents": invoice.total_cents,
        "balance_due_cents": invoice.balance_due_cents,
    }
