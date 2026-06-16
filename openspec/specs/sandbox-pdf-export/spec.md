# sandbox-pdf-export

## Requirements

### Requirement: Sandbox container has PDF rendering dependencies
The Sandbox Docker image SHALL include weasyprint Python package and GTK/Cairo/Pango system runtime libraries required for HTML-to-PDF conversion.

#### Scenario: weasyprint import succeeds in sandbox
- **WHEN** a Python process inside the sandbox container executes `from weasyprint import HTML`
- **THEN** the import SHALL succeed without ImportError or OSError

#### Scenario: PDF generation with CJK text
- **WHEN** a report containing Chinese characters is rendered to PDF via weasyprint
- **THEN** the PDF SHALL display CJK glyphs correctly without tofu (missing character) boxes

#### Scenario: Image size stays within acceptable bounds
- **WHEN** the sandbox Docker image is built with PDF dependencies
- **THEN** the image size increase over the base image SHALL not exceed 250MB

### Requirement: Sandbox PDF rendering is self-contained
All PDF rendering dependencies SHALL be installed directly in the sandbox image at build time, with no runtime download or external service dependency.

#### Scenario: Offline PDF generation
- **WHEN** the sandbox container has no network access
- **THEN** `HTML(string=html).write_pdf()` SHALL still produce a valid PDF file
