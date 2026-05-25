## MODIFIED Requirements

### Requirement: Report navigates back to source thread
The system SHALL allow users to navigate from a report result or artifact back to the originating thread and run context.

#### Scenario: User navigates from report to source thread
- **WHEN** a user views a report result
- **THEN** the UI SHALL display a link that navigates back to the source thread/run that generated it

#### Scenario: User navigates from artifact to source report
- **WHEN** a user views an artifact
- **THEN** the UI SHALL display a link that navigates back to the report run or thread that generated it

## ADDED Requirements

### Requirement: Report run shows data snapshot sources
The system SHALL display the data files produced by data steps as downloadable sources in the report run detail view.

#### Scenario: User downloads data step output from run detail
- **WHEN** a user views a report run detail and data step output files exist
- **THEN** the UI SHALL list the available data files with download links via the artifact API

#### Scenario: No data files available shows empty state
- **WHEN** a report run has no data step output files
- **THEN** the UI SHALL display a placeholder indicating no data sources are available
