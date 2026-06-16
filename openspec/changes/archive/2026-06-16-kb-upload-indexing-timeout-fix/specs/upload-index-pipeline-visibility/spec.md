## MODIFIED Requirements

### Requirement: Upload to index status is visible
The system SHALL display the full pipeline status from upload through indexing completion, including the indexing indicator immediately upon upload success without waiting for the first poll cycle, and SHALL allow users to upload additional files while previous uploads are still indexing.

#### Scenario: User sees indexing progress immediately after upload
- **WHEN** a user uploads a document to a knowledge base and the API returns `index_status: "pending"`
- **THEN** the UI SHALL immediately show the indexing spinner, without a visible gap before the first status poll resolves

#### Scenario: User uploads multiple files concurrently
- **WHEN** a user uploads file A via the file upload form and file A is still indexing
- **THEN** the upload form SHALL remain visible with cleared fields, and the user SHALL be able to select and upload file B, with both files showing their individual indexing status simultaneously in the tracker list

#### Scenario: Text mode keeps existing close-on-submit behavior
- **WHEN** a user creates a document via text input mode
- **THEN** the form SHALL close immediately after successful submission, without adding the document to the concurrent tracker list

#### Scenario: Each tracked document polls independently
- **WHEN** multiple documents are in the tracker list
- **THEN** each document SHALL poll its own index status independently every 2 seconds, stopping when it reaches indexed or failed

#### Scenario: Document list reflects concurrent index states
- **WHEN** one document is indexing and another is queued (pending)
- **THEN** the document list SHALL display the correct badge for each document: indexing for the active one, pending (waiting) for the queued one

#### Scenario: User sees indexing failure reason
- **WHEN** indexing fails for any tracked document
- **THEN** the UI SHALL display the specific failure reason and suggest a recoverable action

#### Scenario: Closing form does not interrupt background indexing
- **WHEN** the user closes the add form while documents are still indexing
- **THEN** the tracker list SHALL unmount, but the document list SHALL continue displaying correct indexing status badges via its own polling, and backend indexing SHALL proceed uninterrupted

#### Scenario: Reopening add form shows clean state
- **WHEN** the user closes and reopens the add form
- **THEN** the new form SHALL start with an empty tracker list; the document list below SHALL show the current status of all documents

## ADDED Requirements

### Requirement: Large file upload timeout resilience
The system SHALL support file uploads up to 20 MB without gateway timeout errors under typical network conditions.

#### Scenario: Large PDF upload completes without timeout
- **WHEN** a user uploads a 15 MB PDF file to a knowledge base
- **THEN** the upload SHALL complete within 600 seconds without a gateway timeout error

#### Scenario: Upload timeout is consistent with other long-running endpoints
- **WHEN** configuring the reverse proxy for any upload endpoint
- **THEN** the proxy timeout settings SHALL match the existing 600-second timeout used for streaming and LangGraph endpoints
