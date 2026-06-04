## ADDED Requirements

### Requirement: Smooth scrolling
The application SHALL use smooth scrolling for all in-page navigation and scroll actions, unless the user prefers reduced motion.

#### Scenario: Anchor link triggers smooth scroll
- **WHEN** user clicks an anchor link pointing to a same-page element
- **THEN** the viewport SHALL smoothly scroll to the target element instead of jumping instantly

#### Scenario: Smooth scroll respects reduced motion
- **WHEN** user has `prefers-reduced-motion: reduce` enabled
- **THEN** scrolling SHALL be instant (no smooth animation)

### Requirement: FeatureCard hover transition
FeatureCard components SHALL include CSS transitions on hover-able properties to ensure smooth visual feedback.

#### Scenario: Hover transition on FeatureCard
- **WHEN** user hovers over a FeatureCard
- **THEN** all visual changes (scale, shadow, background) SHALL animate with a 200ms ease-out transition
- **AND** the transition SHALL not trigger on page load or layout shift

#### Scenario: Reduced motion disables transition
- **WHEN** user has `prefers-reduced-motion: reduce` enabled
- **THEN** hover transitions SHALL be disabled (instant state change)
