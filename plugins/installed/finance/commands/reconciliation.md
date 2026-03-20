---
description: Reconcile GL balances to subledger, bank, or third-party balances
argument-hint: "<account> [period]"
---

# Account Reconciliation

> If you see unfamiliar placeholders or need to check which tools are connected, see [CONNECTORS.md](../CONNECTORS.md).

**Important**: This command assists with reconciliation workflows but does not provide financial advice. All reconciliations should be reviewed by qualified financial professionals before sign-off.

Reconcile GL account balances to subledger, bank, or third-party balances. Identify and categorize reconciling items and generate a reconciliation workpaper.

## Usage

```
/recon <account> <period>
```

### Arguments

- `account` — The account or account category to reconcile. Examples:
  - `cash` or `bank` — Bank reconciliation (GL cash to bank statement)
  - `accounts-receivable` or `ar` — AR subledger reconciliation
  - `accounts-payable` or `ap` — AP subledger reconciliation
  - `fixed-assets` or `fa` — Fixed asset subledger reconciliation
  - `intercompany` or `ic` — Intercompany balance reconciliation
  - `prepaid` — Prepaid expense schedule reconciliation
  - `accrued-liabilities` — Accrued liabilities detail reconciliation
  - Any specific GL account code (e.g., `1010`, `2100`)
- `period` — The accounting period end date (e.g., `2024-12`, `2024-12-31`)

## Workflow

### 1. Gather Both Sides of the Reconciliation

If ~~erp or ~~data warehouse is connected:
- Pull the GL balance for the specified account(s) as of period end
- Pull the subledger, bank statement, or third-party balance for comparison
- Pull prior period reconciliation (if available) for outstanding item carryforward

If no data source is connected:
> Connect ~~erp or ~~data warehouse to pull account balances automatically. To reconcile manually, provide:
> 1. **GL side:** The general ledger balance for the account as of period end
> 2. **Other side:** The subledger balance, bank statement balance, or third-party confirmation balance
> 3. **Prior period outstanding items** (optional): Any reconciling items from the prior period reconciliation

### 2. Compare Balances

Calculate the difference between the two sides:

```
GL Balance:                    $XX,XXX.XX
Subledger/Bank/Other Balance:  $XX,XXX.XX
                               ----------
Difference:                    $XX,XXX.XX
```

### 3. Identify Reconciling Items

Analyze the difference and categorize reconciling items:

**Timing Differences** (items that will clear in subsequent periods):
- Outstanding checks / payments issued but not yet cleared
- Deposits in transit / receipts recorded but not yet credited
- Invoices posted in one system but pending in the other
- Accruals awaiting reversal

**Permanent Differences** (items requiring adjustment):
- Errors in recording (wrong amount, wrong account, duplicate entries)
- Missing entries (transactions in one system but not the other)
- Bank fees or charges not yet recorded
- Foreign currency translation differences

**Prior Period Items** (carryforward from prior reconciliation):
- Items from prior period that have now cleared (remove from reconciliation)
- Items from prior period still outstanding (carry forward with aging)

### 4. Generate Reconciliation Workpaper

```
ACCOUNT RECONCILIATION
Account: [Account code] — [Account name]
Period End: [Date]
Prepared by: [User]
Date Prepared: [Today]

RECONCILIATION SUMMARY
=======================

Balance per General Ledger:              $XX,XXX.XX

Add: Reconciling items increasing GL
  [Item description]                     $X,XXX.XX
  [Item description]                     $X,XXX.XX
                                         ---------
  Subtotal additions:                    $X,XXX.XX

Less: Reconciling items decreasing GL
  [Item description]                    ($X,XXX.XX)
  [Item description]                    ($X,XXX.XX)
                                         ---------
  Subtotal deductions:                  ($X,XXX.XX)

Adjusted GL Balance:                     $XX,XXX.XX

Balance per [Subledger/Bank/Other]:      $XX,XXX.XX

Add: Reconciling items
  [Item description]                     $X,XXX.XX

Less: Reconciling items
  [Item description]                    ($X,XXX.XX)

Adjusted [Other] Balance:                $XX,XXX.XX

DIFFERENCE:                              $0.00
```

### 5. Reconciling Items Detail

Present each reconciling item with:

| # | Description | Amount | Category | Age (Days) | Status | Action Required |
|---|-------------|--------|----------|------------|--------|-----------------|
| 1 | [Detail]    | $X,XXX | Timing   | 5          | Expected to clear | Monitor |
| 2 | [Detail]    | $X,XXX | Error    | N/A        | Requires correction | Post adjusting JE |

### 6. Review and Escalation

Flag items that require attention:

- **Aged items:** Reconciling items outstanding more than 30/60/90 days
- **Large items:** Individual items exceeding materiality thresholds
- **Growing balances:** Reconciling item totals increasing period over period
- **Unresolved prior period items:** Items carried forward without resolution
- **Unexplained differences:** Amounts that cannot be tied to specific transactions

### 7. Output

Provide:
1. The formatted reconciliation workpaper
2. List of reconciling items with categorization and aging
3. Required adjusting entries (if any permanent differences identified)
4. Action items for items requiring follow-up
5. Comparison to prior period reconciliation (if available)
6. Sign-off section for preparer and reviewer
