# PDF OCR Fallback

OCR-based text extraction from image-based/scanned PDFs using PyMuPDF + Tesseract, triggered automatically when the `pdf_converter` is `"auto-with-ocr"` and pymupdf4llm output is too sparse.

## Requirements

### Requirement: OCR-based PDF text extraction
The system SHALL support extracting text from image-based/scanned PDFs via OCR using PyMuPDF + Tesseract when the `pdf_converter` is `"auto-with-ocr"`.

#### Scenario: OCR successfully extracts text from scanned PDF
- **WHEN** a scanned PDF is uploaded and pymupdf4llm produces insufficient text
- **AND** the pdf_converter is `"auto-with-ocr"`
- **AND** Tesseract is installed with the configured language packs
- **THEN** the system SHALL perform OCR on each page and return extracted text

#### Scenario: MarkItDown is skipped in auto-with-ocr mode
- **WHEN** pdf_converter is `"auto-with-ocr"`
- **AND** pymupdf4llm output is detected as sparse
- **THEN** the system SHALL proceed directly to OCR without attempting MarkItDown

#### Scenario: Text PDF does not trigger OCR in auto-with-ocr mode
- **WHEN** pdf_converter is `"auto-with-ocr"`
- **AND** pymupdf4llm produces dense output (>= 50 chars per page, or >= 200 chars total)
- **THEN** the system SHALL return the pymupdf4llm output without running OCR or MarkItDown

#### Scenario: pymupdf4llm not installed, auto-with-ocr mode attempts OCR
- **WHEN** pdf_converter is `"auto-with-ocr"`
- **AND** pymupdf4llm is not installed
- **THEN** the system SHALL attempt OCR via PyMuPDF directly
- **AND** if PyMuPDF is also unavailable, SHALL fall through to MarkItDown and return EMPTY_RESULT if text is insufficient

#### Scenario: OCR produces insufficient text
- **WHEN** OCR is attempted on a low-quality scanned PDF
- **AND** the resulting text is less than 200 non-whitespace characters
- **THEN** the system SHALL return `EMPTY_RESULT` error with the existing image-based/scanned message

#### Scenario: OCR not attempted in non-OCR modes
- **WHEN** the pdf_converter is `"auto"`, `"pymupdf4llm"`, or `"markitdown"`
- **AND** both text extractors produce insufficient text
- **THEN** the system SHALL return `EMPTY_RESULT` without attempting OCR

### Requirement: OCR resource limits
The system SHALL enforce configurable resource limits on OCR processing.

#### Scenario: OCR exceeds page limit
- **WHEN** a scanned PDF has more pages than `ocr_max_pages` (default 50)
- **THEN** the system SHALL OCR only the first `ocr_max_pages` pages and return extracted text for those pages

#### Scenario: OCR exceeds time budget
- **WHEN** OCR per-page processing exceeds `ocr_timeout_seconds` (default 300) tracked by elapsed wall-clock time
- **THEN** the system SHALL stop OCR and return partial text if any pages completed, or `EMPTY_RESULT` if no pages completed
- **AND** the system SHALL log a warning with `"OCR truncated: N/M pages processed (limit=...)"` so operators can tune `ocr_timeout_seconds`

#### Scenario: OCR crashes on a single page
- **WHEN** Tesseract raises an error on a specific page during OCR
- **THEN** the system SHALL log a warning, skip that page, and continue OCR on remaining pages

### Requirement: OCR availability detection
The system SHALL detect whether Tesseract OCR is available at startup and report it via `resolve_pdf_converter()`.

#### Scenario: Tesseract available
- **WHEN** Tesseract is installed and accessible
- **AND** PyMuPDF can invoke Tesseract successfully
- **THEN** `resolve_pdf_converter()` SHALL report `ocr_available: true`

#### Scenario: Tesseract not installed
- **WHEN** Tesseract is not installed or not on PATH
- **AND** pdf_converter is `"auto-with-ocr"`
- **THEN** `resolve_pdf_converter()` SHALL report `ocr_available: false` with a warning message including installation instructions

### Requirement: OCR unavailability error
The system SHALL return a distinct error code when OCR is configured but unavailable.

#### Scenario: OCR unavailable during conversion
- **WHEN** pdf_converter is `"auto-with-ocr"`
- **AND** Tesseract is not installed or fails at runtime
- **THEN** the system SHALL return error code `OCR_UNAVAILABLE` with detail message indicating how to install Tesseract

#### Scenario: OCR unavailable distinguished from EMPTY_RESULT
- **WHEN** an upload fails with `OCR_UNAVAILABLE`
- **THEN** the frontend SHALL display a distinct toast message about server OCR configuration, not the image-based/scanned document message
