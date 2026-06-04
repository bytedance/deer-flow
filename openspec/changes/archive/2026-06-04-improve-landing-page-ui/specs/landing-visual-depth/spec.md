## ADDED Requirements

### Requirement: Landing page background texture
The landing page SHALL render a subtle noise/grain texture overlay behind the main content, providing visual depth without overwhelming the industrial design language.

#### Scenario: Noise texture visible on landing page
- **WHEN** user navigates to the landing page (`/`)
- **THEN** a semi-transparent noise texture overlay is visible behind the hero section and feature cards
- **AND** the texture does not interfere with text readability (contrast ratio >= 4.5:1)

#### Scenario: Texture respects reduced motion
- **WHEN** user has `prefers-reduced-motion: reduce` enabled
- **THEN** the texture SHALL still be visible (it is static, not animated)

#### Scenario: Texture scales with viewport
- **WHEN** viewport is resized from 320px to 2560px width
- **THEN** the texture SHALL cover the full viewport without visible tiling seams or resolution artifacts

### Requirement: FeatureCard hover interaction
Each FeatureCard on the landing page SHALL respond to mouse hover with a subtle scale-up and colored shadow effect.

#### Scenario: Hover on FeatureCard
- **WHEN** user hovers over a FeatureCard
- **THEN** the card scales to `1.02` of its original size over 200ms
- **AND** a colored shadow matching the theme accent appears
- **AND** the card background color shifts slightly lighter

#### Scenario: Hover respects reduced motion
- **WHEN** user has `prefers-reduced-motion: reduce` enabled
- **THEN** the card SHALL NOT animate on hover

### Requirement: Layout asymmetry for hero section
The landing page hero section SHALL introduce controlled asymmetry to break the fully-centered, symmetrical layout.

#### Scenario: Hero section at desktop width
- **WHEN** viewport width >= 1024px
- **THEN** the hero heading and CTA button SHALL be left-aligned
- **AND** supporting text/visual element occupies the right side, creating a two-column asymmetric layout

#### Scenario: Hero section at mobile width
- **WHEN** viewport width < 1024px
- **THEN** the hero content SHALL stack vertically in a centered single-column layout
