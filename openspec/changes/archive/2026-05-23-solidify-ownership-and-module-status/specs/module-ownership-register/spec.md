## ADDED Requirements

### Requirement: Every module has a real owner
The system SHALL maintain an ownership register where every module in the capability matrix has a designated business owner and technical owner.

#### Scenario: Module ownership is traceable
- **WHEN** a cross-module change is proposed
- **THEN** the responsible business owner and technical owner for each affected module SHALL be identifiable from the register

#### Scenario: Unassigned modules are flagged
- **WHEN** a module lacks a confirmed owner
- **THEN** it SHALL be explicitly marked as UNASSIGNED in the register and listed as a management risk
