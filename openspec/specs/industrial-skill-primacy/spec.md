# industrial-skill-primacy Specification

## Purpose
TBD - created by archiving change industrial-intelligence-primary-track. Update Purpose after archive.
## Requirements
### Requirement: Industrial skills cannot be disabled
The system SHALL prevent disabling of skills with `tier=core-industrial` via the standard skill toggle interface. Admins MUST explicitly change the skill tier to `foundation` before disabling.

#### Scenario: Attempt to disable industrial skill via API
- **WHEN** an admin sends `PUT /api/skills/{name}` with `enabled=false` for a skill with `tier=core-industrial`
- **THEN** the system returns HTTP 409 Conflict with message "Industrial skills cannot be disabled. Change tier to foundation first."

#### Scenario: Attempt to disable industrial skill via UI toggle
- **WHEN** an admin views the skill selector with an industrial skill (`tier=core-industrial`)
- **THEN** the enable/disable toggle for that skill is disabled (grayed out) with tooltip "Industrial skills cannot be disabled"

### Requirement: Industrial skills pre-enabled for new tenants
The system SHALL automatically enable all skills with `tier=core-industrial` when a new tenant is created. Tenant admins MAY disable individual industrial skills after changing their tier.

#### Scenario: New tenant creation
- **WHEN** a new tenant is created via `POST /api/tenants`
- **THEN** all skills with `tier=core-industrial` are automatically enabled for that tenant (inserted into tenant skill configuration with `enabled=true`)

#### Scenario: Tenant skill list after creation
- **WHEN** a tenant admin queries `GET /api/skills` immediately after tenant creation
- **THEN** all industrial skills (`tier=core-industrial`) appear with `enabled=true`

### Requirement: Industrial skills appear first in selectors
The system SHALL display skills with `tier=core-industrial` before skills with `tier=foundation` in all skill selection interfaces. Industrial skills SHALL appear in a prominent, non-collapsible section.

#### Scenario: Skill selector ordering
- **WHEN** a user opens the skill selector in a chat or agent configuration
- **THEN** industrial skills (`tier=core-industrial`) appear at the top in a section labeled "Industrial Intelligence", followed by foundation skills in a collapsible "Foundation Tools" section

#### Scenario: Skill search results
- **WHEN** a user searches for skills in the skill selector
- **THEN** search results display industrial skills first, then foundation skills, with visual distinction (industrial skills have industrial-themed icons)

### Requirement: Industrial skill tier cannot be changed via bulk operations
The system SHALL reject bulk tier change operations that attempt to demote industrial skills to foundation without explicit confirmation. Single skill tier changes remain available for legitimate use cases.

#### Scenario: Bulk demote industrial skills
- **WHEN** an admin sends `PUT /api/skills/batch-tier` with multiple industrial skills and `to_tier=foundation`
- **THEN** the system returns HTTP 400 Bad Request with message "Bulk demotion of industrial skills is not allowed. Change tiers individually."

#### Scenario: Single skill tier change
- **WHEN** an admin sends `PUT /api/skills/{name}/tier` with `tier=foundation` for an industrial skill
- **THEN** the system accepts the request and changes the tier (admin can then disable the skill if needed)

### Requirement: Industrial skill protection audit trail
The system SHALL log all attempts to disable or demote industrial skills, including successful tier changes and rejected disable attempts, for security and compliance auditing.

#### Scenario: Tier change audit log
- **WHEN** an admin changes an industrial skill's tier to foundation
- **THEN** the system creates an audit log entry with admin user ID, skill name, old tier, new tier, and timestamp

#### Scenario: Disable attempt audit log
- **WHEN** an admin attempts to disable an industrial skill (rejected by system)
- **THEN** the system creates an audit log entry with admin user ID, skill name, attempted action (disable), and rejection reason

