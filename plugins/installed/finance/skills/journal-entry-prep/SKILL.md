---
name: journal-entry-prep
description: Prepare journal entries with proper debits, credits, and supporting documentation for month-end close. Use when booking accruals, prepaid amortization, fixed asset depreciation, payroll entries, revenue recognition, or any manual journal entry.
---

# Journal Entry Preparation

**Important**: This skill assists with journal entry workflows but does not provide financial advice. All entries should be reviewed by qualified financial professionals before posting.

Best practices, standard entry types, documentation requirements, and review workflows for journal entry preparation.

## Standard Accrual Types and Their Entries

### Accounts Payable Accruals

Accrue for goods or services received but not yet invoiced at period end.

**Typical entry:**
- Debit: Expense account (or capitalize if asset-qualifying)
- Credit: Accrued liabilities

**Sources for calculation:**
- Open purchase orders with confirmed receipts
- Contracts with services rendered but unbilled
- Recurring vendor arrangements (utilities, subscriptions, professional services)
- Employee expense reports submitted but not yet processed

**Key considerations:**
- Reverse in the following period (auto-reversal recommended)
- Use consistent estimation methodology period over period
- Document basis for estimates (PO amount, contract terms, historical run-rate)
- Track actual vs accrual to refine future estimates

### Fixed Asset Depreciation

Book periodic depreciation expense for tangible and intangible assets.

**Typical entry:**
- Debit: Depreciation/amortization expense (by department or cost center)
- Credit: Accumulated depreciation/amortization

**Depreciation methods:**
- **Straight-line:** (Cost - Salvage) / Useful life — most common for financial reporting
- **Declining balance:** Accelerated method applying fixed rate to net book value
- **Units of production:** Based on actual usage or output vs total expected

**Key considerations:**
- Run depreciation from the fixed asset register or schedule
- Verify new additions are set up with correct useful life and method
- Check for disposals or impairments requiring write-off
- Ensure consistency between book and tax depreciation tracking

### Prepaid Expense Amortization

Amortize prepaid expenses over their benefit period.

**Typical entry:**
- Debit: Expense account (insurance, software, rent, etc.)
- Credit: Prepaid expense

**Common prepaid categories:**
- Insurance premiums (typically 12-month policies)
- Software licenses and subscriptions
- Prepaid rent (if applicable under lease terms)
- Prepaid maintenance contracts
- Conference and event deposits

**Key considerations:**
- Maintain an amortization schedule with start/end dates and monthly amounts
- Review for any prepaid items that should be fully expensed (immaterial amounts)
- Check for cancelled or terminated contracts requiring accelerated amortization
- Verify new prepaids are added to the schedule promptly

### Payroll Accruals

Accrue compensation and related costs for the period.

**Typical entries:**

*Salary accrual (for pay periods not aligned with month-end):*
- Debit: Salary expense (by department)
- Credit: Accrued payroll

*Bonus accrual:*
- Debit: Bonus expense (by department)
- Credit: Accrued bonus

*Benefits accrual:*
- Debit: Benefits expense
- Credit: Accrued benefits

*Payroll tax accrual:*
- Debit: Payroll tax expense
- Credit: Accrued payroll taxes

**Key considerations:**
- Calculate salary accrual based on working days in the period vs pay period
- Bonus accruals should reflect plan terms (target amounts, performance metrics, payout timing)
- Include employer-side taxes and benefits (FICA, FUTA, health, 401k match)
- Track PTO/vacation accrual liability if required by policy or jurisdiction

### Revenue Recognition

Recognize revenue based on performance obligations and delivery.

**Typical entries:**

*Recognize previously deferred revenue:*
- Debit: Deferred revenue
- Credit: Revenue

*Recognize revenue with new receivable:*
- Debit: Accounts receivable
- Credit: Revenue

*Defer revenue received in advance:*
- Debit: Cash / Accounts receivable
- Credit: Deferred revenue

**Key considerations:**
- Follow ASC 606 five-step framework for contracts with customers
- Identify distinct performance obligations in each contract
- Determine transaction price (including variable consideration)
- Allocate transaction price to performance obligations
- Recognize revenue as/when performance obligations are satisfied
- Maintain contract-level detail for audit support

## Supporting Documentation Requirements

Every journal entry should have:

1. **Entry description/memo:** Clear, specific description of what the entry records and why
2. **Calculation support:** How amounts were derived (formula, schedule, source data reference)
3. **Source documents:** Reference to the underlying transactions or events (PO numbers, invoice numbers, contract references, payroll register)
4. **Period:** The accounting period the entry applies to
5. **Preparer identification:** Who prepared the entry and when
6. **Approval:** Evidence of review and approval per the authorization matrix
7. **Reversal indicator:** Whether the entry auto-reverses and the reversal date

## Review and Approval Workflows

### Typical Approval Matrix

| Entry Type | Amount Threshold | Approver |
|-----------|-----------------|----------|
| Standard recurring | Any amount | Accounting manager |
| Non-recurring / manual | < $50K | Accounting manager |
| Non-recurring / manual | $50K - $250K | Controller |
| Non-recurring / manual | > $250K | CFO / VP Finance |
| Top-side / consolidation | Any amount | Controller or above |
| Out-of-period adjustments | Any amount | Controller or above |

*Note: Thresholds should be set based on your organization's materiality and risk tolerance.*

### Review Checklist

Before approving a journal entry, the reviewer should verify:

- [ ] Debits equal credits (entry is balanced)
- [ ] Correct accounting period (not posting to a closed period)
- [ ] Account codes exist and are appropriate for the transaction
- [ ] Amounts are mathematically accurate and supported by calculations
- [ ] Description is clear, specific, and sufficient for audit purposes
- [ ] Department/cost center/project coding is correct
- [ ] Treatment is consistent with prior periods and accounting policies
- [ ] Auto-reversal is set appropriately (accruals should reverse)
- [ ] Supporting documentation is complete and referenced
- [ ] Entry amount is within the preparer's authority level
- [ ] No duplicate of an existing entry
- [ ] Unusual or large amounts are explained and justified

## Common Errors to Check For

1. **Unbalanced entries:** Debits do not equal credits (system should prevent, but check manual entries)
2. **Wrong period:** Entry posted to an incorrect or already-closed period
3. **Wrong sign:** Debit entered as credit or vice versa
4. **Duplicate entries:** Same transaction recorded twice (check for duplicates before posting)
5. **Wrong account:** Entry posted to incorrect GL account (especially similar account codes)
6. **Missing reversal:** Accrual entry not set to auto-reverse, causing double-counting
7. **Stale accruals:** Recurring accruals not updated for changed circumstances
8. **Round-number estimates:** Suspiciously round amounts that may not reflect actual calculations
9. **Incorrect FX rates:** Foreign currency entries using wrong exchange rate or date
10. **Missing intercompany elimination:** Entries between entities without corresponding elimination
11. **Capitalization errors:** Expenses that should be capitalized, or capitalized items that should be expensed
12. **Cut-off errors:** Transactions recorded in the wrong period based on delivery or service date
