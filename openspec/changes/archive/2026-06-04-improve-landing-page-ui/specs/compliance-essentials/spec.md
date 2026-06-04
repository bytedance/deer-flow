## ADDED Requirements

### Requirement: Privacy policy and terms of service links
The Footer component SHALL display links to privacy policy and terms of service pages, visible on all pages that render the Footer.

#### Scenario: Footer renders legal links
- **WHEN** any page containing the Footer is rendered
- **THEN** links labeled "隐私政策" and "服务条款" are displayed in the footer
- **AND** each link navigates to its respective page when clicked

#### Scenario: Legal links are visually distinct
- **WHEN** the Footer renders
- **THEN** the legal links SHALL be separated from the copyright info by at least 8px of vertical spacing
- **AND** the links SHALL use `text-muted-foreground` color, with `hover:text-foreground` transition

### Requirement: Cookie consent banner
The application SHALL display a cookie consent banner on first visit, in compliance with Chinese data privacy regulations.

#### Scenario: First visit shows cookie banner
- **WHEN** user visits the site for the first time (no `cookie-consent` key in localStorage)
- **THEN** a fixed bottom banner is displayed with a brief cookie usage notice
- **AND** the banner contains an "我知道了" (I understand) dismiss button

#### Scenario: Dismissed banner does not reappear
- **WHEN** user clicks "我知道了" on the cookie banner
- **THEN** the banner disappears
- **AND** a `cookie-consent` entry is stored in localStorage with value `"true"`
- **AND** the banner SHALL NOT appear on subsequent page loads

#### Scenario: Banner does not block critical content
- **WHEN** the cookie banner is displayed
- **THEN** it SHALL have `position: fixed; bottom: 0` and not affect page layout
- **AND** all interactive elements behind it remain accessible once dismissed
