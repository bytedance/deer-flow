---
name: audit-support
description: Support SOX 404 compliance with control testing methodology, sample selection, and documentation standards. Use when generating testing workpapers, selecting audit samples, classifying control deficiencies, or preparing for internal or external audits.
---

# Audit Support

**Important**: This skill assists with SOX compliance workflows but does not provide audit or legal advice. All testing workpapers and assessments should be reviewed by qualified financial professionals. While "significance" and "materiality" are context-specific concepts that are ultimately assessed by auditors, this skill is intended to assist professionals in the creation and evaluation of effective internal controls and documentation for audits.

SOX 404 control testing methodology, sample selection approaches, testing documentation standards, control deficiency classification, and common control types.

## SOX 404 Control Testing Methodology

### Overview

SOX Section 404 requires management to assess the effectiveness of internal controls over financial reporting (ICFR). This involves:

1. **Scoping:** Identify significant accounts and relevant assertions
2. **Risk assessment:** Evaluate the risk of material misstatement for each significant account
3. **Control identification:** Document the controls that address each risk
4. **Testing:** Test the design and operating effectiveness of key controls
5. **Evaluation:** Assess whether any deficiencies exist and their severity
6. **Reporting:** Document the assessment and any material weaknesses

### Scoping Significant Accounts

An account is significant if there is more than a remote likelihood that it could contain a misstatement that is material (individually or in aggregate).

**Quantitative factors:**
- Account balance exceeds materiality threshold (typically 3-5% of a key benchmark)
- Transaction volume is high, increasing the risk of error
- Account is subject to significant estimates or judgment

**Qualitative factors:**
- Account involves complex accounting (revenue recognition, derivatives, pensions)
- Account is susceptible to fraud (cash, revenue, related-party transactions)
- Account has had prior misstatements or audit adjustments
- Account involves significant management judgment or estimates
- New account or significantly changed process

### Relevant Assertions by Account Type

| Account Type | Key Assertions |
|-------------|---------------|
| Revenue | Occurrence, Completeness, Accuracy, Cut-off |
| Accounts Receivable | Existence, Valuation (allowance), Rights |
| Inventory | Existence, Valuation, Completeness |
| Fixed Assets | Existence, Valuation, Completeness, Rights |
| Accounts Payable | Completeness, Accuracy, Existence |
| Accrued Liabilities | Completeness, Valuation, Accuracy |
| Equity | Completeness, Accuracy, Presentation |
| Financial Close/Reporting | Presentation, Accuracy, Completeness |

### Design Effectiveness vs Operating Effectiveness

**Design effectiveness:** Is the control properly designed to prevent or detect a material misstatement in the relevant assertion?
- Evaluated through walkthroughs (trace a transaction end-to-end through the process)
- Confirm the control is placed at the right point in the process
- Confirm the control addresses the identified risk
- Performed at least annually, or when processes change

**Operating effectiveness:** Did the control actually operate as designed throughout the testing period?
- Evaluated through testing (inspection, observation, re-performance, inquiry)
- Requires sufficient sample sizes to support a conclusion
- Must cover the full period of reliance

## Sample Selection Approaches

### Random Selection

**When to use:** Default method for transaction-level controls with large populations.

**Method:**
1. Define the population (all transactions subject to the control during the period)
2. Number each item in the population sequentially
3. Use a random number generator to select sample items
4. Ensure no bias in selection (all items have equal probability)

**Advantages:** Statistically valid, defensible, no selection bias
**Disadvantages:** May miss high-risk items, requires complete population listing

### Targeted (Judgmental) Selection

**When to use:** Supplement to random selection for risk-based testing; primary method when population is small or highly varied.

**Method:**
1. Identify items with specific risk characteristics:
   - High dollar amount (above a defined threshold)
   - Unusual or non-standard transactions
   - Period-end transactions (cut-off risk)
   - Related-party transactions
   - Manual or override transactions
   - New vendor/customer transactions
2. Select items matching risk criteria
3. Document rationale for each targeted selection

**Advantages:** Focuses on highest-risk items, efficient use of testing effort
**Disadvantages:** Not statistically representative, may over-represent certain risks

### Haphazard Selection

**When to use:** When random selection is impractical (no sequential population listing) and population is relatively homogeneous.

**Method:**
1. Select items without any specific pattern or bias
2. Ensure selections are spread across the full population period
3. Avoid unconscious bias (don't always pick items at the top, round numbers, etc.)

**Advantages:** Simple, no technology required
**Disadvantages:** Not statistically valid, susceptible to unconscious bias

### Systematic Selection

**When to use:** When population is sequential and you want even coverage across the period.

**Method:**
1. Calculate the sampling interval: Population size / Sample size
2. Select a random starting point within the first interval
3. Select every Nth item from the starting point

**Example:** Population of 1,000, sample of 25 → interval of 40. Random start: item 17. Select items 17, 57, 97, 137, ...

**Advantages:** Even coverage across population, simple to execute
**Disadvantages:** Periodic patterns in the population could bias results

### Sample Size Guidance

| Control Frequency | Expected Population | Low Risk Sample | Moderate Risk Sample | High Risk Sample |
|------------------|--------------------|-----------------|--------------------|-----------------|
| Annual | 1 | 1 | 1 | 1 |
| Quarterly | 4 | 2 | 2 | 3 |
| Monthly | 12 | 2 | 3 | 4 |
| Weekly | 52 | 5 | 8 | 15 |
| Daily | ~250 | 20 | 30 | 40 |
| Per-transaction (small pop.) | < 250 | 20 | 30 | 40 |
| Per-transaction (large pop.) | 250+ | 25 | 40 | 60 |

**Factors increasing sample size:**
- Higher inherent risk in the account/process
- Control is the sole control addressing a significant risk (no redundancy)
- Prior period control deficiency identified
- New control (not tested in prior periods)
- External auditor reliance on management testing

## Testing Documentation Standards

### Workpaper Requirements

Every control test should be documented with:

1. **Control identification:**
   - Control number/ID
   - Control description (what is done, by whom, how often)
   - Control type (manual, automated, IT-dependent manual)
   - Control frequency
   - Risk and assertion addressed

2. **Test design:**
   - Test objective (what you are trying to determine)
   - Test procedures (step-by-step instructions)
   - Expected evidence (what you expect to see if the control is effective)
   - Sample selection methodology and rationale

3. **Test execution:**
   - Population description and size
   - Sample selection details (method, items selected)
   - Results for each sample item (pass/fail with specific evidence examined)
   - Exceptions noted with full description

4. **Conclusion:**
   - Overall assessment (effective / deficiency / significant deficiency / material weakness)
   - Basis for conclusion
   - Impact assessment for any exceptions
   - Compensating controls considered (if applicable)

5. **Sign-off:**
   - Tester name and date
   - Reviewer name and date

### Evidence Standards

**Sufficient evidence includes:**
- Screenshots showing system-enforced controls
- Signed/initialed approval documents
- Email approvals with identifiable approver and date
- System audit logs showing who performed the action and when
- Re-performed calculations with matching results
- Observation notes (with date, location, observer)

**Insufficient evidence:**
- Verbal confirmations alone (must be corroborated)
- Undated documents
- Evidence without identifiable performer/approver
- Generic system reports without date/time stamps
- "Per discussion with [name]" without corroborating documentation

### Working Paper Organization

Organize testing files by control area:

```
SOX Testing/
├── [Year]/
│   ├── Scoping and Risk Assessment/
│   ├── Revenue Cycle/
│   │   ├── Control Matrix
│   │   ├── Walkthrough Documentation
│   │   ├── Test Workpapers (one per control)
│   │   └── Supporting Evidence
│   ├── Procure to Pay/
│   ├── Payroll/
│   ├── Financial Close/
│   ├── Treasury/
│   ├── Fixed Assets/
│   ├── IT General Controls/
│   ├── Entity Level Controls/
│   └── Summary and Conclusions/
│       ├── Deficiency Evaluation
│       └── Management Assessment
```

## Control Deficiency Classification

### Deficiency

A deficiency in internal control exists when the design or operation of a control does not allow management or employees, in the normal course of performing their assigned functions, to prevent or detect misstatements on a timely basis.

**Evaluation factors:**
- What is the likelihood that the control failure could result in a misstatement?
- What is the magnitude of the potential misstatement?
- Is there a compensating control that mitigates the deficiency?

### Significant Deficiency

A deficiency, or combination of deficiencies, that is less severe than a material weakness yet important enough to merit attention by those charged with governance.

**Indicators:**
- The deficiency could result in a misstatement that is more than inconsequential but less than material
- There is more than a remote (but less than reasonably possible) likelihood of a material misstatement
- The control is a key control and the deficiency is not fully mitigated by compensating controls
- Combination of individually minor deficiencies that together represent a significant concern

### Material Weakness

A deficiency, or combination of deficiencies, such that there is a reasonable possibility that a material misstatement of the financial statements will not be prevented or detected on a timely basis.

**Indicators:**
- Identification of fraud by senior management (any magnitude)
- Restatement of previously issued financial statements to correct a material error
- Identification by the auditor of a material misstatement that would not have been detected by the company's controls
- Ineffective oversight of financial reporting by the audit committee
- Deficiency in a pervasive control (entity-level, IT general control) affecting multiple processes

### Deficiency Aggregation

Individual deficiencies that are not significant individually may be significant in combination:

1. Identify all deficiencies in the same process or affecting the same assertion
2. Evaluate whether the combined effect could result in a material misstatement
3. Consider whether deficiencies in compensating controls exacerbate other deficiencies
4. Document the aggregation analysis and conclusion

### Remediation

For each identified deficiency:

1. **Root cause analysis:** Why did the control fail? (design gap, execution failure, staffing, training, system issue)
2. **Remediation plan:** Specific actions to fix the control (redesign, additional training, system enhancement, added review)
3. **Timeline:** Target date for remediation completion
4. **Owner:** Person responsible for implementing the remediation
5. **Validation:** How and when the remediated control will be re-tested to confirm effectiveness

## Common Control Types

### IT General Controls (ITGCs)

Controls over the IT environment that support the reliable functioning of application controls and automated processes.

**Access Controls:**
- User access provisioning (new access requests require approval)
- User access de-provisioning (terminated users removed timely)
- Privileged access management (admin/superuser access restricted and monitored)
- Periodic access reviews (user access recertified on a defined schedule)
- Password policies (complexity, rotation, lockout)
- Segregation of duties enforcement (conflicting access prevented)

**Change Management:**
- Change requests documented and approved before implementation
- Changes tested in a non-production environment before promotion
- Separation of development and production environments
- Emergency change procedures (documented, approved post-implementation)
- Change review and post-implementation validation

**IT Operations:**
- Batch job monitoring and exception handling
- Backup and recovery procedures (regular backups, tested restores)
- System availability and performance monitoring
- Incident management and escalation procedures
- Disaster recovery planning and testing

### Manual Controls

Controls performed by people using judgment, typically involving review and approval.

**Examples:**
- Management review of financial statements and key metrics
- Supervisory approval of journal entries above a threshold
- Three-way match verification (PO, receipt, invoice)
- Account reconciliation preparation and review
- Physical inventory observation and count
- Vendor master data change approval
- Customer credit approval

**Key attributes to test:**
- Was the control performed by the right person (proper authority)?
- Was it performed timely (within the required timeframe)?
- Is there evidence of the review (signature, initials, email, system log)?
- Did the reviewer have sufficient information to perform an effective review?
- Were exceptions identified and appropriately addressed?

### Automated Controls

Controls enforced by IT systems without human intervention.

**Examples:**
- System-enforced approval workflows (cannot proceed without required approvals)
- Three-way match automation (system blocks payment if PO/receipt/invoice don't match)
- Duplicate payment detection (system flags or blocks duplicate invoices)
- Credit limit enforcement (system prevents orders exceeding credit limit)
- Automated calculations (depreciation, amortization, interest, tax)
- System-enforced segregation of duties (conflicting roles prevented)
- Input validation controls (required fields, format checks, range checks)
- Automated reconciliation matching

**Testing approach:**
- Test design: Confirm the system configuration enforces the control as intended
- Test operating effectiveness: For automated controls, if the system configuration has not changed, one test of the control is typically sufficient for the period (supplemented by ITGC testing of change management)
- Verify change management ITGCs are effective (if system changed, re-test the control)

### IT-Dependent Manual Controls

Manual controls that rely on the completeness and accuracy of system-generated information.

**Examples:**
- Management review of a system-generated exception report
- Supervisor review of a system-generated aging report to assess reserves
- Reconciliation using system-generated trial balance data
- Approval of transactions identified by a system-generated workflow

**Testing approach:**
- Test the manual control (review, approval, follow-up on exceptions)
- AND test the completeness and accuracy of the underlying report/data (IPE — Information Produced by the Entity)
- IPE testing confirms the data the reviewer relied on was complete and accurate

### Entity-Level Controls

Broad controls that operate at the organizational level and affect multiple processes.

**Examples:**
- Tone at the top / code of conduct
- Risk assessment process
- Audit committee oversight of financial reporting
- Internal audit function and activities
- Fraud risk assessment and anti-fraud programs
- Whistleblower/ethics hotline
- Management monitoring of control effectiveness
- Financial reporting competence (staffing, training, qualifications)
- Period-end financial reporting process (close procedures, GAAP compliance reviews)

**Significance:**
- Entity-level controls can mitigate but typically cannot replace process-level controls
- Ineffective entity-level controls (especially audit committee oversight and tone at the top) are strong indicators of a material weakness
- Effective entity-level controls may reduce the extent of testing needed for process-level controls
