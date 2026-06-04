## ADDED Requirements

### Requirement: Skip-to-content link
The application SHALL provide a keyboard-accessible skip-to-content link at the top of every page, allowing keyboard users to bypass navigation.

#### Scenario: Skip link becomes visible on keyboard focus
- **WHEN** user presses Tab on page load
- **THEN** a "跳转到主要内容" link SHALL become visible at the top of the page
- **AND** the link SHALL be styled with high contrast against the background

#### Scenario: Skip link navigates to main content
- **WHEN** user activates the skip link (Enter or click)
- **THEN** focus SHALL move to the `<main>` element
- **AND** the URL hash SHALL update to `#main-content`

#### Scenario: Skip link is hidden by default
- **WHEN** no keyboard interaction has occurred
- **THEN** the skip link SHALL be visually hidden (screen-reader only) using the `sr-only` pattern
- **AND** the link remains accessible to screen readers

### Requirement: Custom 404 page
The application SHALL render a branded, helpful 404 page when users navigate to non-existent routes.

#### Scenario: User navigates to non-existent route
- **WHEN** user navigates to a URL that has no matching route (e.g., `/nonexistent`)
- **THEN** a custom 404 page is displayed
- **AND** the page SHALL include the EHM branding (logo or name)
- **AND** a link back to the landing page (`/`) is provided

#### Scenario: 404 page on workspace routes
- **WHEN** user navigates to a non-existent `/workspace/*` route
- **THEN** the 404 page SHALL still display correctly within the workspace layout context
- **AND** a link to `/workspace/chats` is provided in addition to `/`
