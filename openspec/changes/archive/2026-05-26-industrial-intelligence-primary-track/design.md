## Context

The `focus-industrial-intelligence` change established industrial intelligence as a featured capability with skill tiering (`core-industrial` vs `foundation`), onboarding flows, telemetry tracking, and a feature flag (`NEXT_PUBLIC_INDUSTRIAL_FIRST`) for gradual rollout. Telemetry data shows strong adoption (industrial skills >60% of invocations, onboarding completion >70%), validating the strategic direction.

However, the current implementation treats industrial-first as an experiment that can be rolled back. The feature flag, conditional logic, and "foundation fallback" paths signal that industrial intelligence is optional rather than definitive. This creates cognitive overhead for users (why is there a "skip to foundation" option?) and maintenance burden (dual-path logic throughout the codebase).

This change transitions industrial intelligence from "featured experiment" to "platform identity"—removing rollback capability, simplifying conditional logic, and establishing industrial-first as the permanent default experience.

**Stakeholders**:
- End users: Expect industrial workflows to be the primary path
- Tenant admins: Need to understand that industrial skills are pre-enabled and protected
- Product team: Industrial-first is the strategic direction, not an A/B test
- Engineering: Simplify codebase by removing feature flag conditionals

## Goals / Non-Goals

**Goals:**
- Establish industrial intelligence as the permanent, non-optional default experience
- Remove all `industrial_first` feature flag logic and conditional branches
- Simplify skill selector, onboarding, and navigation to industrial-first paths
- Protect industrial skills from accidental disablement (require explicit admin action)
- Shift telemetry from "balance tracking" to "adoption depth tracking"
- Update documentation to reflect industrial-first as the definitive direction

**Non-Goals:**
- Removing foundation skills entirely (they remain available as secondary utilities)
- Forcing existing tenants to change their current configuration (migration is opt-in for existing setups)
- Redesigning the onboarding flow from scratch (simplify existing flow by removing "skip to foundation" option)
- Changing the skill tier data model (keep `core-industrial` / `foundation` distinction)

## Decisions

### 1. Feature Flag Removal Strategy

**Decision**: Remove `NEXT_PUBLIC_INDUSTRIAL_FIRST` feature flag entirely. Hardcode all conditional logic to the industrial-first path.

**Rationale**: Feature flags are for experiments. Industrial intelligence is no longer an experiment—it's the strategic direction. Keeping the flag creates false expectation of rollback capability and adds maintenance burden.

**Alternatives considered**:
- **Keep flag but default to true**: Still implies rollback is possible, adds cognitive overhead
- **Deprecate flag gradually**: Unnecessary complexity; clean removal is simpler
- **Move flag to backend config**: Still treats industrial-first as optional

**Implementation**:
- Delete `NEXT_PUBLIC_INDUSTRIAL_FIRST` from `src/env.js`
- Remove all `isIndustrialFirst()` checks in frontend code
- Inline the industrial-first branch, delete fallback branches
- Update `frontend/src/lib/feature-flags.ts` to remove industrial-related exports

### 2. Skill Protection Mechanism

**Decision**: Industrial skills (`tier=core-industrial`) cannot be disabled via the standard skill toggle UI. Admins must explicitly change the tier to `foundation` before disabling.

**Rationale**: Prevents accidental disablement of core platform capabilities. Makes the "industrial is primary" decision explicit and visible.

**Alternatives considered**:
- **Soft warning on disable**: Users can still accidentally confirm and disable
- **Admin-only disable**: Still allows disablement without tier change, less explicit
- **No protection**: Risks tenants accidentally disabling core industrial capabilities

**Implementation**:
- Backend: `PUT /api/skills/{name}` rejects `enabled=false` when `tier=core-industrial`, returns 409 with message "Change tier to foundation before disabling"
- Frontend: Skill selector disables the toggle for `core-industrial` skills, shows tooltip "Industrial skills cannot be disabled"
- Admin UI: Tier change dropdown remains available, but disable toggle is hidden until tier is changed

### 3. Onboarding Flow Simplification

**Decision**: Remove the "skip to foundation" option from the industrial onboarding overlay. Users either complete the industrial onboarding or close the overlay entirely (which still marks onboarding as complete).

**Rationale**: The "skip to foundation" option implies that foundation is an equally valid starting point. Removing it reinforces that industrial intelligence is the primary path.

**Alternatives considered**:
- **Keep skip option but de-emphasize**: Still signals dual-track approach
- **Remove onboarding entirely**: Loses the guided introduction to industrial workflows
- **Make onboarding mandatory**: Too aggressive, users may want to skip

**Implementation**:
- Remove "Skip to Foundation Tools" button from `industrial-onboarding-overlay.tsx`
- Keep "Skip Onboarding" button (closes overlay, marks `industrial_onboarding_completed=true`)
- Update onboarding telemetry: remove `onboarding_skip_to_foundation` event type

### 4. Default Agent Configuration

**Decision**: New custom agents created via fork or bootstrap inherit industrial-first defaults: industrial skills pre-enabled, industrial prompt templates as default, industrial tools prioritized in tool list.

**Rationale**: Ensures that even user-created agents align with the industrial-first platform identity. Reduces friction for users creating industrial-focused agents.

**Alternatives considered**:
- **No defaults, let user configure**: Adds friction, users may not discover industrial capabilities
- **Industrial defaults only for "industrial" agent templates**: Limits discoverability for users creating general-purpose agents
- **Industrial defaults with easy opt-out**: Good, but opt-out should be explicit (not accidental)

**Implementation**:
- `POST /api/agents/fork/{name}`: When forking, if source agent has industrial skills enabled, preserve them. If source has no skills, add default industrial skills (`vibration-fault-diagnosis`, `ins-device-analysis`, `monitoring-analysis`)
- `SOUL.md` template for new agents: Include industrial context section by default
- Agent creation UI: "Industrial Agent" template is the first option, "General Agent" is secondary

### 5. Telemetry Shift: Balance → Adoption Depth

**Decision**: Shift industrial skills telemetry from tracking "industrial vs foundation balance" to tracking "industrial workflow adoption depth". New metrics: industrial workflow completion rate, time-to-value for industrial tasks, industrial template usage, industrial agent creation rate.

**Rationale**: Balance metrics made sense during the experiment phase (are we achieving 60% industrial usage?). Now that industrial-first is permanent, we need to measure whether industrial workflows are delivering value, not just usage counts.

**Alternatives considered**:
- **Keep balance metrics**: No longer relevant; industrial-first is not a balance, it's the default
- **Remove telemetry entirely**: Loses visibility into adoption and value delivery
- **Add adoption metrics alongside balance**: Adds noise; balance metrics are no longer meaningful

**Implementation**:
- Backend: Add new telemetry event types to `industrial_skills_telemetry.py`:
  - `industrial_workflow_completed` (workflow_type, duration_seconds, success)
  - `industrial_template_used` (template_id, report_run_id)
  - `industrial_agent_created` (agent_name, skills_enabled_count)
- Frontend: Update telemetry tracking calls in skill invocation, template usage, agent creation flows
- Dashboard: Replace "industrial vs foundation pie chart" with "industrial workflow adoption funnel"

### 6. Navigation Hierarchy Restructure

**Decision**: Promote industrial workflows to top-level navigation positions. Move "Device Management", "Monitoring Analysis", and "Diagnosis Reports" to primary nav. Demote "General Chat", "Research", and "Data Analysis" to secondary "Tools" menu.

**Rationale**: Navigation structure signals platform priorities. Industrial-first means industrial workflows are immediately accessible, not buried in submenus.

**Alternatives considered**:
- **Keep current nav, add industrial shortcuts**: Doesn't fully signal industrial-first priority
- **Separate industrial and foundation nav**: Creates false equivalence, implies dual-track
- **User-customizable nav**: Good for power users, but default should be industrial-first

**Implementation**:
- Frontend: Update `workspace-nav.tsx` to reorder nav items:
  1. Device Management (industrial)
  2. Monitoring Analysis (industrial)
  3. Diagnosis Reports (industrial)
  4. Report Templates (industrial-focused)
  5. Tools (collapsible: General Chat, Research, Data Analysis, Image Generation)
- Update nav icons to industrial-themed for top-level items

### 7. Template Marketplace Featured Category

**Decision**: Create a dedicated "Industrial Intelligence" featured category in the template marketplace. Industrial templates (equipment diagnosis, monitoring, trend analysis) appear first in search results and have a dedicated landing page.

**Rationale**: Template marketplace is a key discovery mechanism. Featuring industrial templates reinforces industrial-first positioning and improves discoverability.

**Alternatives considered**:
- **Tag industrial templates, no dedicated category**: Less visible, requires users to filter
- **Separate industrial marketplace**: Over-engineering, fragments the marketplace
- **Industrial templates only**: Too restrictive, foundation templates still have value

**Implementation**:
- Backend: Add `is_featured` boolean to template metadata, auto-set to `true` for templates with `category=industrial`
- Frontend: Update marketplace listing to show featured category first, add "Industrial Intelligence" landing page with curated template list
- Search: Boost industrial templates in search ranking (add `category=industrial` to search boost logic)

### 8. Migration Strategy for Existing Tenants

**Decision**: Existing tenants retain their current skill enablement state. Provide a one-time migration prompt: "Industrial intelligence is now the default. Enable recommended industrial skills?" Accepting enables all `core-industrial` skills; declining keeps current state.

**Rationale**: Respects existing tenant configuration while offering a clear upgrade path. Avoids forcing changes that might disrupt existing workflows.

**Alternatives considered**:
- **Force-enable industrial skills for all tenants**: Disruptive, may break existing workflows
- **No migration, only new tenants get defaults**: Misses opportunity to upgrade existing tenants
- **Silent background migration**: Non-transparent, violates user expectations

**Implementation**:
- Backend: Add `industrial_migration_prompted` boolean to tenant preferences
- Frontend: On next login, if `industrial_migration_prompted=false`, show migration dialog
- Migration action: `POST /api/tenants/{id}/migrate-industrial` enables all `core-industrial` skills, sets `industrial_migration_prompted=true`
- Skip action: Sets `industrial_migration_prompted=true`, no skill changes

## Risks / Trade-offs

**[Risk] Existing tenants resist industrial-first defaults**
→ Mitigation: Migration is opt-in for existing tenants. Only new tenants get industrial defaults. Provide clear documentation explaining the strategic direction and benefits.

**[Risk] Removing feature flag makes rollback impossible if industrial-first fails**
→ Mitigation: Telemetry shows strong adoption (>60% industrial usage, >70% onboarding completion). Industrial-first is validated. If critical issues emerge, code can be reverted via git, but this is a strategic decision, not an experiment.

**[Risk] Skill protection mechanism frustrates admins who want to disable industrial skills**
→ Mitigation: Protection is explicit (requires tier change, not just toggle). Admin UI clearly explains why protection exists. Tier change is available for legitimate use cases (e.g., tenant doesn't need industrial capabilities).

**[Risk] Navigation restructure confuses existing users**
→ Mitigation: Migration prompt includes navigation change explanation. Provide "classic nav" preference for users who prefer the old layout (stored in user preferences, not a feature flag).

**[Trade-off] Simplification vs flexibility**: Removing the feature flag and conditional logic reduces flexibility (no rollback) but simplifies the codebase and makes the strategic direction clear. This is acceptable because industrial-first is a strategic decision, not an experiment.

**[Trade-off] Protection vs admin control**: Skill protection limits admin control (can't directly disable industrial skills) but prevents accidental disablement of core platform capabilities. This is acceptable because admins can still change the tier, which is an explicit action.

## Migration Plan

1. **Feature flag removal**: Delete `NEXT_PUBLIC_INDUSTRIAL_FIRST` from env config, remove all conditional logic, inline industrial-first branches
2. **Skill protection**: Backend API rejects disable for `core-industrial` skills, frontend disables toggle
3. **Onboarding simplification**: Remove "skip to foundation" button, update telemetry
4. **Agent defaults**: Update fork/creation logic to inherit industrial defaults
5. **Telemetry shift**: Add adoption depth metrics, remove balance metrics
6. **Navigation restructure**: Reorder nav items, promote industrial workflows
7. **Template marketplace**: Add featured category, boost industrial templates in search
8. **Existing tenant migration**: Add migration prompt, respect opt-in/opt-out choice

**Rollback strategy**: None. This is a permanent strategic decision. If critical issues emerge, code can be reverted via git, but the expectation is that industrial-first is the definitive direction.

## Open Questions

None. The strategic direction is clear: industrial intelligence is the primary track. All technical decisions support this direction.
