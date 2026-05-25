## ADDED Requirements

### Requirement: Run record links to template version snapshot
The system SHALL allow users to navigate from a report run to the exact template version DSL that produced it.

#### Scenario: User views template version from run detail
- **WHEN** a user views a report run detail page and the run has a `template_version`
- **THEN** the UI SHALL display a link to the specific template version page (`/workspace/report-templates/{template_id}?version={template_version}`) that shows the DSL snapshot

#### Scenario: Builtin template run shows version ref
- **WHEN** a report run was produced by a builtin template (template_version is null and template_version_ref is set)
- **THEN** the UI SHALL display the `template_version_ref` (e.g., `abc123def-1`) as a readable, non-clickable label

#### Scenario: Run list shows template version column
- **WHEN** a user views the report runs list
- **THEN** each row SHALL display the template version or version ref that produced that run
