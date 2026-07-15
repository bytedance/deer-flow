SWEB-COMPLEX-001: invoice totals disagree across the billing package.

Observed behavior:
- line discounts are ignored for subtotal and tax;
- tax is rounded by truncation instead of currency half-up rounding;
- tax-exempt lines are included in taxable subtotal;
- refunded payments are not removed from the balance calculation;
- reporting marks overpaid or fully settled invoices incorrectly.

Expected behavior is documented by `tests/test_invoice_pipeline.py`.
