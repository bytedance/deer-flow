## ADDED Requirements

### Requirement: Each industry-related capability has a layer classification
The system SHALL classify every industry-related capability as belonging to Core Platform, Enterprise Control Plane, or Industry Solution Layer.

#### Scenario: InS auth capability is classified
- **WHEN** the boundary review is complete
- **THEN** InS authentication SHALL have an explicit classification (Core Platform, Enterprise Control Plane, or Industry Solution Layer) with rationale

#### Scenario: Classification covers all current industry capabilities
- **WHEN** the review is finalized
- **THEN** the classification SHALL cover at minimum: InS authentication, organization, devices, industry reports, and diagnosis pipelines
