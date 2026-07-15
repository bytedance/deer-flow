from __future__ import annotations

from billing import InvoiceLine, build_invoice
from billing.reporting import summarize_invoice


def test_invoice_pipeline_applies_discount_tax_exemption_refunds_and_status():
    invoice = build_invoice(
        [
            InvoiceLine("consulting", 1999, 2, discount_cents=299, taxable=True),
            InvoiceLine("book", 2500, 1, taxable=False),
        ],
        tax_rate_bps=825,
        payments_cents=[2000],
        refunds_cents=[500],
    )

    assert invoice.subtotal_cents == 6199
    assert invoice.taxable_subtotal_cents == 3699
    assert invoice.tax_cents == 305
    assert invoice.total_cents == 6504
    assert invoice.balance_due_cents == 5004
    assert summarize_invoice(invoice) == {
        "status": "partial",
        "subtotal_cents": 6199,
        "tax_cents": 305,
        "total_cents": 6504,
        "balance_due_cents": 5004,
    }


def test_discount_cannot_make_negative_tax_and_overpayment_is_settled():
    invoice = build_invoice(
        [InvoiceLine("warranty-credit", 100, 1, discount_cents=250, taxable=True)],
        tax_rate_bps=825,
        payments_cents=[1],
    )

    assert invoice.subtotal_cents == 0
    assert invoice.taxable_subtotal_cents == 0
    assert invoice.tax_cents == 0
    assert invoice.balance_due_cents == -1
    assert summarize_invoice(invoice)["status"] == "paid"
