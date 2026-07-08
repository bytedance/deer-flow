## ADDED Requirements

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

### Requirement: KB-level aggregated index statistics
The system SHALL aggregate per-document indexing status into knowledge-base-level statistics accessible via API.

#### Scenario: KB list endpoint includes index summary
- **WHEN** a user lists knowledge bases via `GET /api/knowledge-bases`
- **THEN** each returned KB entry SHALL carry `document_count`, `indexed_count`, and `failed_count` computed from the KB's documents

#### Scenario: KB detail endpoint includes index detail
- **WHEN** a user requests `GET /api/knowledge-bases/{id}`
- **THEN** the response SHALL include per-status document counts, last index timestamp, and recent failure entries

### Requirement: Failure classification in pipeline visibility
The system SHALL classify index failures displayed in the pipeline view by standardized error categories, including OCR-specific errors.

#### Scenario: Failed document shows classified error type
- **WHEN** a document's index_status is "failed"
- **THEN** the UI SHALL display the classified failure type alongside the raw error message

#### Scenario: KB detail groups failures by type
- **WHEN** a knowledge base has multiple failed documents
- **THEN** the index stats SHALL group failures by category (e.g., "EMPTY_RESULT: 3, ENCRYPTED_PDF: 1, OCR_UNAVAILABLE: 2")

#### Scenario: OCR_UNAVAILABLE is distinguished from EMPTY_RESULT
- **WHEN** a document fails with `OCR_UNAVAILABLE`
- **THEN** the UI SHALL display a distinct message about server OCR misconfiguration, not the image-based/scanned document message

### Requirement: Large file upload timeout resilience
The system SHALL support file uploads up to 20 MB without gateway timeout errors under typical network conditions.

#### Scenario: Large PDF upload completes without timeout
- **WHEN** a user uploads a 15 MB PDF file to a knowledge base
- **THEN** the upload SHALL complete within 600 seconds without a gateway timeout error

#### Scenario: Upload timeout is consistent with other long-running endpoints
- **WHEN** configuring the reverse proxy for any upload endpoint
- **THEN** the proxy timeout settings SHALL match the existing 600-second timeout used for streaming and LangGraph endpoints

### Requirement: OCR availability visible in admin converter status
The system SHALL report OCR availability and configuration in the admin converter status endpoint.

#### Scenario: Admin checks converter status with OCR available
- **WHEN** an admin queries `resolve_pdf_converter()`
- **AND** pdf_converter is `"auto-with-ocr"`
- **AND** Tesseract is installed and accessible
- **THEN** the response SHALL include `ocr_available: true`, `ocr_languages: "<configured>"`, `ocr_max_pages: <configured>`, and `ocr_timeout_seconds: <configured>`

#### Scenario: Admin checks converter status with OCR unavailable
- **WHEN** an admin queries `resolve_pdf_converter()`
- **AND** pdf_converter is `"auto-with-ocr"`
- **AND** Tesseract is not installed
- **THEN** the response SHALL include `ocr_available: false` and a warning message with Tesseract installation instructions
