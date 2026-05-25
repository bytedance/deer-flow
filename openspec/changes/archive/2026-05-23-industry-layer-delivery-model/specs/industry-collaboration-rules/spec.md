## ADDED Requirements

### Requirement: Collaboration rules are defined
The system SHALL define collaboration rules, change impact boundaries, and responsibility assignments resulting from the delivery model decision.

#### Scenario: Collaboration model is clear
- **WHEN** a developer on the platform team makes a change that affects the industry layer
- **THEN** the collaboration rules SHALL specify who needs to be notified, who approves, and who executes the corresponding industry-layer change

#### Scenario: Change responsibility is assigned
- **WHEN** an industry-layer capability needs maintenance
- **THEN** the responsibility SHALL be clearly assigned to either the industry team, the platform team, or a shared ownership model
