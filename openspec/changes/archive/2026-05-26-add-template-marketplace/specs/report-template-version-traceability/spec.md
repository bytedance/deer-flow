## MODIFIED Requirements

### Requirement: Run record links to template version snapshot
The system SHALL allow users to navigate from a report run to the exact template version DSL that produced it, including templates installed from the marketplace.

#### Scenario: User views template version from run detail
- **WHEN** a user views a report run detail page and the run has a `template_version`
- **THEN** the UI SHALL display a link to the specific template version page (`/workspace/report-templates/{template_id}?version={template_version}`) that shows the DSL snapshot

#### Scenario: Builtin template run shows version ref
- **WHEN** a report run was produced by a builtin template (template_version is null and template_version_ref is set)
- **THEN** the UI SHALL display the `template_version_ref` (e.g., `abc123def-1`) as a readable, non-clickable label

#### Scenario: Run list shows template version column
- **WHEN** a user views the report runs list
- **THEN** each row SHALL display the template version or version ref that produced that run

#### Scenario: Marketplace-installed template shows source badge
- **WHEN** a report run was produced by a template installed from the marketplace
- **THEN** the UI SHALL display a "Marketplace" badge next to the template name, and the template version link SHALL point to the installed copy (not the upstream marketplace listing)

### Requirement: Template fork tracks marketplace source
The system SHALL record the marketplace source template ID and version when a template is installed from the marketplace.

#### Scenario: Fork from marketplace records source
- **WHEN** a user installs a template from the marketplace via `POST /api/template-marketplace/{id}/install`
- **THEN** the forked template's metadata SHALL include `marketplace_source: { template_id, version, installed_at }` fields

#### Scenario: Upstream update notification
- **WHEN** a marketplace template publishes a new version and a user has installed an older version
- **THEN** the system SHALL display an "Update available" badge on the installed template's detail page with a link to view the changelog and update

#### Scenario: Template detail shows marketplace origin
- **WHEN** a user views the detail page of a template installed from the marketplace
- **THEN** the UI SHALL display "Installed from marketplace" with a link to the marketplace listing and the installed version number
