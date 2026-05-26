## ADDED Requirements

### Requirement: Visual form step editor
The system SHALL provide a drag-and-drop interface for creating and editing form steps, supporting all field types defined in DSL v1 (text, textarea, number, date, select, checkbox, multi-select).

#### Scenario: Add form step via drag-and-drop
- **WHEN** user drags a "Form Step" block from the component palette onto the canvas
- **THEN** the system SHALL create a new form step with a default title and one default text field, and display it in the step list

#### Scenario: Reorder form steps
- **WHEN** user drags a form step to a new position in the step list
- **THEN** the system SHALL update the `next` field of all affected steps to maintain the correct chain, and persist the new order in the DSL

#### Scenario: Configure form field properties
- **WHEN** user clicks on a form field in the editor
- **THEN** the system SHALL display a property panel with controls for: name, label, type, required, default, placeholder, description, options (for select/multi-select), and validation rules

#### Scenario: Add dynamic options source
- **WHEN** user configures a select/multi-select field and selects "Dynamic options"
- **THEN** the system SHALL display inputs for: source step (dropdown of prior steps), JSONPath, label field, value field, and group field

### Requirement: Visual section editor
The system SHALL provide a visual editor for report sections, supporting all component types (markdown, card, card_group, echart, table, image, closure_section).

#### Scenario: Add section via drag-and-drop
- **WHEN** user drags a section component from the palette onto the section canvas
- **THEN** the system SHALL create a new section with a default title and prompt the user to configure the source JSONPath

#### Scenario: Configure section source
- **WHEN** user selects a section in the editor
- **THEN** the system SHALL display a source picker that shows available data paths from data_steps and transforms outputs, with JSONPath autocomplete

#### Scenario: Preview section layout
- **WHEN** user has configured sections with valid sources
- **THEN** the system SHALL display a read-only preview of the report layout showing section titles, component types, and sample data structure

### Requirement: Real-time DSL validation
The system SHALL validate the template against DSL v1 schema on every edit and display errors inline.

#### Scenario: Validation error on invalid step reference
- **WHEN** user configures a section source that references a non-existent step ID
- **THEN** the system SHALL highlight the section in red, display the validator error message, and prevent publishing until the error is resolved

#### Scenario: Validation success indicator
- **WHEN** all template fields pass validation
- **THEN** the system SHALL display a green checkmark and enable the "Publish" button

### Requirement: YAML toggle view
The system SHALL allow users to switch between visual editor and raw YAML editor.

#### Scenario: Switch to YAML view
- **WHEN** user clicks "YAML" tab
- **THEN** the system SHALL serialize the current DSL to YAML format and display it in a syntax-highlighted code editor

#### Scenario: Edit in YAML view and return to visual
- **WHEN** user edits YAML and clicks "Visual" tab
- **THEN** the system SHALL parse the YAML, validate against DSL schema, and update the visual editor. If parsing fails, display the error and remain in YAML view

### Requirement: Template save and publish from editor
The system SHALL allow users to save drafts and publish templates directly from the editor.

#### Scenario: Save draft
- **WHEN** user clicks "Save Draft"
- **THEN** the system SHALL call `POST /api/report-templates/` (create) or `PUT /api/report-templates/{id}` (update) with the current DSL, and display a success toast

#### Scenario: Publish template
- **WHEN** user clicks "Publish" and validation passes
- **THEN** the system SHALL call `POST /api/report-templates/{id}/publish` and redirect to the template detail page

#### Scenario: Publish blocked by validation errors
- **WHEN** user clicks "Publish" and validation has errors
- **THEN** the system SHALL scroll to the first error, highlight it, and display a banner "Fix all errors before publishing"

### Requirement: Editor component palette
The system SHALL provide a component palette listing all available building blocks.

#### Scenario: Palette displays available components
- **WHEN** user opens the editor
- **THEN** the palette SHALL display: Form Step, Device Selector Step, Section (with sub-types: markdown, card, card_group, echart, table, image, closure_section), and Data Step (advanced)

#### Scenario: Palette filters by context
- **WHEN** user is editing the sections area
- **THEN** the palette SHALL only show section components, not form steps
