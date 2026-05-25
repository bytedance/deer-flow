## ADDED Requirements

### Requirement: Every module has an assigned owner
The system SHALL maintain a documented ownership record for each module in the capability matrix, with both a business owner and a technical owner identified by name or confirmed role.

#### Scenario: Module has confirmed owners
- **WHEN** a module's business and technical owners have been confirmed by the relevant stakeholders
- **THEN** the capability matrix SHALL list the confirmed owner names or roles with the status "已确认"

#### Scenario: Module owner is pending confirmation
- **WHEN** a module's owner is known by role but the specific person is not yet confirmed
- **THEN** the capability matrix SHALL list the role name with the annotation "[待确认人员]" and mark the ownership status as "待确认"

#### Scenario: Module has no identified owner
- **WHEN** no owner can be identified for a module during the review cycle
- **THEN** the module SHALL be flagged as "无主" in the ownership status column and listed in a separate management risk register

### Requirement: Every module has a lifecycle state
The system SHALL assign each module one of four lifecycle states: Core, Scale-Up, Stabilize, or Incubate, reflecting the current product and engineering maturity.

#### Scenario: Core module identification
- **WHEN** a module is essential to the primary user workflow and requires guaranteed stability
- **THEN** its state SHALL be set to "Core"

#### Scenario: Scale-Up module identification
- **WHEN** a module is production-usable but needs scale and governance improvements
- **THEN** its state SHALL be set to "Scale-Up"

#### Scenario: Stabilize module identification
- **WHEN** a module exists but needs boundary convergence, lifecycle completion, or experience unification
- **THEN** its state SHALL be set to "Stabilize"

#### Scenario: Incubate module identification
- **WHEN** a module's direction is validated but still under exploration or product boundary definition
- **THEN** its state SHALL be set to "Incubate"

### Requirement: Every module has a Q3 investment decision
The system SHALL record an explicit investment decision for each module for the current quarter: continue investment, maintain, reduce, or stop.

#### Scenario: Investment decision recorded
- **WHEN** the quarterly review is complete
- **THEN** each module SHALL have one of four investment conclusions: "继续投入", "维持", "缩减", or "停投"

#### Scenario: Un-owned module investment is suspended
- **WHEN** a module has no confirmed owner
- **THEN** its investment conclusion SHALL default to "暂停 — 待定责" until ownership is resolved

### Requirement: Ownership ledger is usable for monthly review
The system SHALL produce an ownership ledger document that can be directly referenced in monthly architecture and planning reviews.

#### Scenario: Monthly review references the ledger
- **WHEN** a monthly review or planning session occurs
- **THEN** the ledger SHALL provide clear answers to: who owns each module, what state it is in, and whether investment continues

#### Scenario: Ledger identifies management risks
- **WHEN** modules have unresolved ownership, unclear state, or stopped investment
- **THEN** these SHALL be explicitly surfaced as management risks in a dedicated section of the ledger
