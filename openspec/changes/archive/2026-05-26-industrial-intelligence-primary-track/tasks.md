# Industrial Intelligence Primary Track - Implementation Tasks

## 1. Feature Flag Removal

- [x] 1.1 Remove `NEXT_PUBLIC_INDUSTRIAL_FIRST` from `frontend/src/env.js`
- [x] 1.2 Remove `isIndustrialFirst()` function from `frontend/src/lib/feature-flags.ts`
- [x] 1.3 Remove all `isIndustrialFirst()` checks in skill selector components, inline industrial-first branch
- [x] 1.4 Remove all `isIndustrialFirst()` checks in onboarding overlay, inline industrial-first branch
- [x] 1.5 Remove all `isIndustrialFirst()` checks in navigation components, inline industrial-first branch
- [x] 1.6 Remove `industrial_first` from backend tenant preferences model
- [x] 1.7 Update admin documentation to remove feature flag references
- [x] 1.8 Write tests to verify feature flag removal (no conditional logic remains)

## 2. Skill Protection Mechanism

- [x] 2.1 Backend: Update `PUT /api/skills/{name}` to reject `enabled=false` when `tier=core-industrial` (return 409)
- [x] 2.2 Backend: Update `PUT /api/skills/batch-tier` to reject bulk demotion of industrial skills (return 400)
- [x] 2.3 Backend: Add audit log entries for tier changes and disable attempts
- [x] 2.4 Frontend: Update skill selector to disable toggle for `core-industrial` skills with tooltip
- [x] 2.5 Frontend: Add confirmation dialog for single skill tier change from industrial to foundation
- [x] 2.6 Backend: Add `POST /api/tenants/{id}/migrate-industrial` endpoint to enable all industrial skills
- [x] 2.7 Backend: Add `industrial_migration_prompted` boolean to tenant preferences
- [x] 2.8 Write tests for skill protection (disable rejection, bulk demotion rejection, audit logging)

## 3. Onboarding Flow Simplification

- [x] 3.1 Remove "Skip to Foundation Tools" button from `industrial-onboarding-overlay.tsx`
- [x] 3.2 Update onboarding telemetry to remove `onboarding_skip_to_foundation` event type
- [x] 3.3 Update onboarding step 5 to navigate to industrial workspace (not general workspace)
- [x] 3.4 Update onboarding overlay to show industrial-first messaging throughout
- [x] 3.5 Write E2E tests for simplified onboarding flow (complete onboarding, skip onboarding)

## 4. Agent Defaults

- [x] 4.1 Update `POST /api/agents/fork/{name}` to pre-enable industrial skills when source has no skills
- [x] 4.2 Update default SOUL.md template to include industrial context section
- [x] 4.3 Update agent creation UI to show "Industrial Agent" as first template option
- [x] 4.4 Update agent tool ordering to prioritize industrial tools when industrial skills are enabled
- [x] 4.5 Backend: Add `industrial_agent_created` telemetry event emission on agent creation
- [x] 4.6 Write tests for agent inheritance (fork with skills, fork without skills, bootstrap)

## 5. Telemetry Shift: Balance → Adoption Depth

- [x] 5.1 Backend: Add `industrial_workflow_completed` event type to telemetry model
- [x] 5.2 Backend: Add `industrial_template_used` event type to telemetry model
- [x] 5.3 Backend: Add `industrial_agent_created` event type to telemetry model
- [x] 5.4 Backend: Remove `industrial_percentage` and `by_tier` from telemetry summary response
- [x] 5.5 Backend: Add `workflow_completions`, `template_usage_count`, `agent_creation_count` to summary
- [x] 5.6 Backend: Implement adoption funnel computation (5 stages)
- [x] 5.7 Backend: Implement time-to-value computation (median, 25th, 75th percentile)
- [x] 5.8 Backend: Add `GET /api/telemetry/industrial-skills/adoption-funnel` endpoint
- [x] 5.9 Backend: Add `GET /api/telemetry/industrial-skills/time-to-value` endpoint
- [x] 5.10 Frontend: Update telemetry tracking calls to emit new event types
- [x] 5.11 Frontend: Remove balance-based telemetry tracking calls
- [x] 5.12 Write tests for new telemetry events and adoption funnel computation

## 6. Navigation Hierarchy Restructure

- [x] 6.1 Update `workspace-nav.tsx` to reorder nav items (industrial workflows first)
- [x] 6.2 Create collapsible "Tools" menu component for general tools
- [x] 6.3 Update nav icons to industrial-themed for top-level items
- [x] 6.4 Add navigation state persistence (Tools menu expanded/collapsed) to localStorage
- [x] 6.5 Lock industrial workflow items in navigation customization (cannot be hidden)
- [x] 6.6 Add deep links to industrial workflows from landing page
- [x] 6.7 Update landing page to show "Quick Access" links to industrial workflows
- [x] 6.8 Write tests for navigation ordering, collapsible menu, and state persistence

## 7. Template Marketplace Featured Category

- [x] 7.1 Backend: Add `is_featured` boolean to template metadata model
- [x] 7.2 Backend: Auto-set `is_featured=true` for templates with `category=industrial`
- [x] 7.3 Backend: Update marketplace search to boost industrial templates in ranking
- [x] 7.4 Backend: Add industrial template usage tracking (install count, run count)
- [x] 7.5 Frontend: Create "Industrial Intelligence" featured section on marketplace landing page
- [x] 7.6 Frontend: Create dedicated industrial templates landing page at `/workspace/template-marketplace/industrial`
- [x] 7.7 Frontend: Update marketplace search results to show industrial templates first with "Featured" badge
- [ ] 7.8 Frontend: Add industrial template recommendations based on skill usage (last 7 days)
- [x] 7.9 Write tests for featured category, search boost, and template recommendations

## 8. Existing Tenant Migration

- [x] 8.1 Backend: Add migration prompt logic (check `industrial_migration_prompted` on login)
- [x] 8.2 Frontend: Create migration dialog component with accept/decline options
- [x] 8.3 Frontend: Show migration dialog on first login for tenants with `industrial_migration_prompted=false`
- [x] 8.4 Backend: Implement migration acceptance (enable all industrial skills, set `industrial_migration_completed=true`)
- [x] 8.5 Backend: Implement migration decline (set `industrial_migration_completed=true`, no skill changes)
- [x] 8.6 Write E2E tests for migration flow (accept, decline, already migrated)

## 9. Documentation Updates

- [ ] 9.1 Update user guide to use industrial scenarios as primary examples
- [x] 9.2 Update API documentation to feature industrial use cases
- [x] 9.3 Update admin guide to remove rollback sections and feature flag references
- [ ] 9.4 Update help tooltips to describe industrial workflows
- [ ] 9.5 Create migration guide for existing tenants

## 10. Testing and Validation

- [x] 10.1 E2E test: New user flow (industrial-first landing, onboarding, skill selector, navigation)
- [x] 10.2 E2E test: Existing tenant migration flow (prompt, accept, decline)
- [x] 10.3 E2E test: Skill protection (attempt to disable industrial skill, tier change, audit log)
- [x] 10.4 Integration test: Telemetry shift (new events, adoption funnel, time-to-value)
- [x] 10.5 Integration test: Agent defaults (fork with/without skills, industrial template)
- [ ] 10.6 Performance test: Verify no regression from feature flag removal and conditional logic simplification
