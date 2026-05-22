## ADDED Requirements

### Requirement: Each module has status and investment direction
The system SHALL classify each module as Core, Scale-Up, Stabilize, or Incubate, with a clear investment conclusion for the current cycle.

#### Scenario: Module status is classified
- **WHEN** a stakeholder reviews the capability matrix
- **THEN** each module SHALL display its classification (Core/Scale-Up/Stabilize/Incubate) and investment direction (Invest/Maintain/Reduce/Deprecate)

#### Scenario: Status guides scheduling decisions
- **WHEN** a new feature request is evaluated
- **THEN** the module's status and investment direction SHALL inform whether to proceed, defer, or reject the request
