## ADDED Requirements

### Requirement: Run detail shows trigger context
The system SHALL display the originating conversation that triggered the report generation.

#### Scenario: User navigates from run to source chat
- **WHEN** a user views a report run detail page and the run has a `thread_id`
- **THEN** the UI SHALL display a clearly labeled "Source Chat" link that navigates to the originating thread

#### Scenario: Run without thread context shows placeholder
- **WHEN** a report run has no `thread_id`
- **THEN** the UI SHALL display a placeholder indicating no source context is available

### Requirement: Run detail shows input parameters
The system SHALL display the input parameters used for report generation, including a download link for the raw parameters file when available.

#### Scenario: Parameters section shows raw parameters download link
- **WHEN** a report run has a `parameters_path` pointing to an existing file
- **THEN** the UI SHALL provide a download link for the raw parameters file via the artifact API

#### Scenario: Parameters path missing shows parameters summary only
- **WHEN** a report run has no `parameters_path` or the file does not exist
- **THEN** the UI SHALL display the `parameters_summary` JSON without a download link

### Requirement: Run detail shows available data files
The system SHALL list the data files produced by data steps and make them downloadable.

#### Scenario: Data files list shows available step outputs
- **WHEN** a report run's output directory contains JSON files from data steps
- **THEN** the run detail page SHALL list the available data files with download links via the artifact API

#### Scenario: Data directory missing shows empty state
- **WHEN** a report run's data directory does not exist or contains no files
- **THEN** the UI SHALL display a placeholder indicating no data files are available
