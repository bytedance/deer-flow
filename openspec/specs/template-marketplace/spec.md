## ADDED Requirements

### Requirement: Template marketplace listing
The system SHALL provide a browsable marketplace page displaying published templates with metadata, ratings, and install counts.

#### Scenario: Browse marketplace
- **WHEN** user navigates to `/workspace/template-marketplace`
- **THEN** the system SHALL display a grid of template cards, each showing: display_name, description, author, rating (stars), install count, and tags

#### Scenario: Filter by visibility
- **WHEN** user selects a visibility filter (builtin / tenant / community)
- **THEN** the system SHALL display only templates matching the selected visibility level

#### Scenario: Search templates
- **WHEN** user types a search query in the marketplace search box
- **THEN** the system SHALL perform full-text search on template name, description, and tags, and display matching results ranked by relevance and rating

### Requirement: Template detail page
The system SHALL provide a detail page for each marketplace template with full description, version history, reviews, and install action.

#### Scenario: View template detail
- **WHEN** user clicks on a template card in the marketplace
- **THEN** the system SHALL navigate to `/workspace/template-marketplace/{template_id}` and display: full description, DSL preview (read-only), version history, user reviews, and "Install" button

#### Scenario: View version history
- **WHEN** user clicks "Version History" tab on template detail page
- **THEN** the system SHALL display a list of all published versions with version number, publish date, and changelog

### Requirement: Template install from marketplace
The system SHALL allow users to install marketplace templates into their private or tenant space.

#### Scenario: Install to private space
- **WHEN** user clicks "Install" on a marketplace template and selects "My Templates"
- **THEN** the system SHALL fork the template into the user's private space via `POST /api/report-templates/{id}/fork`, record the install in the marketplace, and redirect to the user's template list

#### Scenario: Install to tenant space
- **WHEN** a tenant admin clicks "Install" and selects "Tenant Templates"
- **THEN** the system SHALL fork the template into the tenant space, record the install, and redirect to the tenant template list

#### Scenario: Install records upstream version
- **WHEN** a template is installed from the marketplace
- **THEN** the system SHALL record the source template ID and version number in the forked template's metadata for update tracking

### Requirement: Template publish to marketplace
The system SHALL allow template authors to publish their templates to the marketplace.

#### Scenario: Publish private template to marketplace
- **WHEN** template owner clicks "Publish to Marketplace" on their private template
- **THEN** the system SHALL prompt for: visibility (tenant / community), description, tags, and screenshot. After confirmation, create a marketplace listing linked to the template

#### Scenario: Tenant admin approval required
- **WHEN** a non-admin user publishes a template with tenant visibility
- **THEN** the system SHALL create a pending listing that requires tenant admin approval before becoming visible in the marketplace

#### Scenario: Update marketplace listing
- **WHEN** template author publishes a new version of a template that has a marketplace listing
- **THEN** the system SHALL automatically update the marketplace listing with the new version and notify users who installed the previous version

### Requirement: Template rating and reviews
The system SHALL allow users to rate and review installed templates.

#### Scenario: Submit rating
- **WHEN** user who installed a template clicks "Rate" and selects 1-5 stars with optional text review
- **THEN** the system SHALL save the rating and review, update the template's average rating, and display the new review in the review list

#### Scenario: Only installed users can review
- **WHEN** user who has not installed the template attempts to rate
- **THEN** the system SHALL display "Install this template to leave a review" and disable the rating form

### Requirement: Template categories and tags
The system SHALL organize marketplace templates by categories and tags for discovery.

#### Scenario: Browse by category
- **WHEN** user selects a category (e.g., "设备日报", "故障诊断", "趋势分析")
- **THEN** the system SHALL filter the marketplace to show only templates in that category

#### Scenario: Tag-based filtering
- **WHEN** user clicks on a tag (e.g., "rotating", "pump", "weekly")
- **THEN** the system SHALL filter the marketplace to show templates with that tag

### Requirement: Marketplace API
The system SHALL provide REST API endpoints for marketplace operations.

#### Scenario: List marketplace templates
- **WHEN** client calls `GET /api/template-marketplace/` with optional query params (search, category, tag, visibility, sort)
- **THEN** the system SHALL return a paginated list of marketplace listings with metadata

#### Scenario: Get marketplace template detail
- **WHEN** client calls `GET /api/template-marketplace/{template_id}`
- **THEN** the system SHALL return the full listing details including reviews, version history, and install count

#### Scenario: Submit review via API
- **WHEN** authenticated user calls `POST /api/template-marketplace/{template_id}/reviews` with rating and comment
- **THEN** the system SHALL save the review and return the created review object

#### Scenario: Install template via API
- **WHEN** authenticated user calls `POST /api/template-marketplace/{template_id}/install` with target (private/tenant)
- **THEN** the system SHALL fork the template, record the install, and return the new template ID
