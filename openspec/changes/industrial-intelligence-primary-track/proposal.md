## Why

Industrial intelligence has emerged as the primary value proposition and competitive advantage of the DeerFlow platform. While the `focus-industrial-intelligence` change (57 tasks completed) established the foundation—skill tiering, onboarding flows, telemetry—the product still treats industrial and foundation capabilities as parallel tracks rather than establishing industrial intelligence as the definitive primary track. This change codifies industrial-first as the permanent strategic direction, ensuring all future product decisions, architectural choices, and user experiences reinforce industrial intelligence as the core platform identity.

## What Changes

- **Default experience**: New users land directly in industrial intelligence workflows without requiring onboarding opt-in. Industrial skills, templates, and agents become the default starting point.
- **Skill hierarchy**: Elevate `core-industrial` skills from "featured" to "primary"—they appear first in all selectors, are pre-enabled for new tenants, and cannot be disabled without explicit admin action.
- **Template marketplace**: Industrial report templates (equipment diagnosis, monitoring analysis, trend reports) become the featured category with dedicated discovery paths.
- **Agent defaults**: New custom agents inherit industrial-first configuration—industrial skills pre-enabled, industrial prompts as default templates, industrial tools prioritized.
- **Navigation structure**: Industrial workflows (device management, monitoring, diagnosis) move to top-level navigation positions. Foundation tools (general research, data analysis) become secondary utilities.
- **Telemetry focus**: Shift monitoring from "industrial vs foundation balance" to "industrial adoption depth"—track which industrial workflows drive value, not just usage counts.
- **Documentation and examples**: All user-facing documentation, examples, and tutorials use industrial scenarios as the primary narrative.
- **Feature flag removal**: Remove the `industrial_first` feature flag—industrial-first is no longer an experiment, it's the permanent direction.

## Capabilities

### New Capabilities

- `industrial-default-experience`: Establish industrial intelligence as the default user journey from first login through daily workflows
- `industrial-skill-primacy`: Codify industrial skills as the primary tier with elevated visibility, pre-enablement, and protection from accidental disablement
- `industrial-template-discovery`: Create dedicated discovery paths for industrial report templates in the marketplace
- `industrial-agent-inheritance`: Ensure new custom agents inherit industrial-first configuration by default
- `industrial-navigation-hierarchy`: Restructure navigation to prioritize industrial workflows at top-level positions
- `industrial-adoption-metrics`: Shift telemetry from balance-tracking to depth-tracking, measuring industrial workflow adoption and value delivery

### Modified Capabilities

- `focus-industrial-intelligence`: Transition from experimental feature flag to permanent platform configuration. Remove rollback capability.

## Impact

**Frontend**:
- Skill selector components: Industrial skills become non-collapsible primary section
- Onboarding flow: Simplified to industrial-first path (remove "skip to foundation" option)
- Navigation: Industrial workflows promoted to top-level positions
- Template marketplace: Industrial category featured with dedicated landing page
- Feature flag removal: `NEXT_PUBLIC_INDUSTRIAL_FIRST` becomes hardcoded `true`

**Backend**:
- Skill API: `core-industrial` tier becomes default for new skills
- Agent creation: Default configuration includes industrial skills and prompts
- Telemetry: Shift from balance metrics to adoption depth metrics
- Template marketplace: Industrial templates featured in discovery endpoints

**Configuration**:
- Remove `industrial_first` feature flag from `env.js` and all conditional logic
- Update `config.yaml` defaults to industrial-first settings
- Migration script for existing tenants: auto-enable industrial skills if not already enabled

**Documentation**:
- User guides: Rewrite examples with industrial scenarios as primary narrative
- API documentation: Industrial use cases featured in all examples
- Admin guide: Remove "rollback to foundation-first" sections
