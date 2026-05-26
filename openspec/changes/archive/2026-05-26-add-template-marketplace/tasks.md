# Tasks

## 1. Foundation & Schema

- [x] 1.1 Define blueprint definition schema (BlueprintDefinition Pydantic model with base_dsl, user_configurable, recommended_scripts, preview_sections)
- [x] 1.2 Add marketplace permission constants to `app/gateway/authz.py`: `MARKETPLACE_READ`, `MARKETPLACE_WRITE`, `MARKETPLACE_PUBLISH` with default grants to superadmin + tenant_admin
- [x] 1.3 Create marketplace database schema as Alembic migration `005_add_marketplace.py`: `MarketplaceListingRow`, `MarketplaceReviewRow`, `MarketplaceInstallRecordRow` (follow `*Row` naming convention and inherit from `persistence.base.Base`)
- [x] 1.4 Define `.template` package format (ZIP structure: template.yaml, metadata.json, blueprint.json, README.md)
- [x] 1.5 Generate initial blueprints from existing 8 builtin templates (reverse-engineer blueprint definitions)

## 2. Blueprint Backend

- [x] 2.1 Create blueprint repository module (`report_templates/blueprint_repository.py`) for filesystem-based blueprint storage
- [x] 2.2 Implement blueprint CRUD operations (list, get, create from builtin template)
- [x] 2.3 Add `GET /api/template-blueprints/` route — list available blueprints with metadata
- [x] 2.4 Add `GET /api/template-blueprints/{id}` route — get full blueprint definition
- [x] 2.5 Add `POST /api/template-blueprints/{id}/create-template` route — create template draft from blueprint
- [x] 2.6 Write blueprint API tests (list, get, create-template, error cases)

## 3. Marketplace Backend

- [x] 3.1 Create marketplace repository module (`report_templates/marketplace_repository.py`) with PostgreSQL-backed CRUD
- [x] 3.2 Implement marketplace listing operations (publish, update, search, filter, paginate)
- [x] 3.3 Implement review operations (create review, list reviews, aggregate rating) — `MarketplaceReviewRow` follows `FeedbackRow` pattern (template_id + user_id + rating + comment + tenant_id)
- [x] 3.4 Implement install operation (fork template + record install + track marketplace source in template metadata)
- [x] 3.5 Add `GET /api/template-marketplace/` route — paginated listing with search/filter/sort (require `marketplace:read`)
- [x] 3.6 Add `GET /api/template-marketplace/{id}` route — detail with reviews and version history
- [x] 3.7 Add `POST /api/template-marketplace/{id}/reviews` route — submit rating and review (require `marketplace:write`)
- [x] 3.8 Add `POST /api/template-marketplace/{id}/install` route — install template to private/tenant space (require `marketplace:write`)
- [x] 3.9 Add `POST /api/report-templates/{id}/publish-to-marketplace` route — create marketplace listing (require `marketplace:publish`)
- [x] 3.10 Add tenant admin approval workflow for non-admin marketplace publishes
- [x] 3.11 Write marketplace API tests (listing, search, install, review, approval flow)

## 4. Template Package Import/Export

- [x] 4.1 Implement `.template` package serializer (DSL + metadata → ZIP)
- [x] 4.2 Implement `.template` package deserializer (ZIP → DSL + metadata, with validation)
- [x] 4.3 Add `GET /api/report-templates/{id}/export` route — download template package
- [x] 4.4 Add `POST /api/report-templates/import` route — upload and import template package
- [x] 4.5 Write import/export tests (round-trip, invalid package, conflict resolution)

## 5. Frontend — Visual Template Editor Core

- [x] 5.1 Install @dnd-kit/core and @dnd-kit/sortable dependencies
- [x] 5.2 Create editor page route (`/workspace/report-templates/editor/[id]`)
- [x] 5.3 Build DSL state management hook (useTemplateDSL) with in-memory DSL object as single source of truth — reuse existing `core/report-templates/api.ts` TanStack Query hooks for CRUD operations
- [x] 5.4 Build editor layout shell (palette sidebar, canvas area, property panel, YAML toggle tab)
- [x] 5.5 Implement real-time validation integration (call `POST /api/report-templates/{id}/validate` on DSL change, display inline errors)
- [x] 5.6 Implement YAML toggle view (serialize DSL to YAML, parse YAML back to DSL, syntax highlighting)

## 6. Frontend — Form Step Editor

- [x] 6.1 Build form step drag-and-drop list (sortable with @dnd-kit)
- [x] 6.2 Build form field property panel (name, label, type, required, default, placeholder, description)
- [x] 6.3 Implement field type-specific controls (select options editor, multi-select options, dynamic options source picker)
- [x] 6.4 Implement device-selector-multi step configuration panel (type_id_from, max_select)
- [x] 6.5 Implement before_step configuration (script name picker from script registry, args editor)
- [x] 6.6 Implement form step reorder with automatic `next` chain update

## 7. Frontend — Section Editor

- [x] 7.1 Build section drag-and-drop canvas
- [x] 7.2 Build section property panel (id, title, component type selector)
- [x] 7.3 Implement source JSONPath autocomplete (populate from data_steps + transforms outputs)
- [x] 7.4 Implement closure_section filters editor (device_ids, statuses, period, page_size)
- [x] 7.5 Implement read-only report layout preview (section titles + component type icons + sample structure)

## 8. Frontend — Data Steps & Transforms (Advanced)

- [x] 8.1 Build data steps form editor (id, script name from registry, args key-value editor, outputs mapping)
- [x] 8.2 Build transforms form editor (id, script name, input source picker, args, outputs)
- [x] 8.3 Implement script registry browser (fetch available scripts, display with descriptions)

## 9. Frontend — Editor Actions

- [x] 9.1 Implement "Save Draft" action (call create/update API, show toast)
- [x] 9.2 Implement "Publish" action (validate, call publish API, redirect on success, scroll-to-error on failure)
- [x] 9.3 Implement "Publish to Marketplace" action (prompt for visibility, description, tags; call marketplace publish API)
- [x] 9.4 Implement "Export .template" action (download template package)
- [x] 9.5 Add unsaved changes warning (beforeunload + navigation guard)

## 10. Frontend — Template Marketplace

- [x] 10.1 Create marketplace page route (`/workspace/template-marketplace`)
- [x] 10.2 Build marketplace grid layout (template cards with name, description, rating, install count, tags)
- [x] 10.3 Implement search bar with full-text search
- [x] 10.4 Implement filter sidebar (visibility, category, tags)
- [x] 10.5 Implement sort controls (rating, installs, newest, relevance)
- [x] 10.6 Create template detail page (`/workspace/template-marketplace/[id]`) — extend existing `core/report-templates/api.ts` with marketplace-specific TanStack Query hooks
- [x] 10.7 Build detail page tabs (description, DSL preview, version history, reviews)
- [x] 10.8 Implement "Install" action with target picker (private / tenant) — reuse existing `useForkReportTemplate` hook
- [x] 10.9 Build review submission form (star rating + text comment)
- [x] 10.10 Implement marketplace listing creation flow from template editor

## 11. Frontend — Blueprint System

- [x] 11.1 Create template creation page with blueprint catalog (`/workspace/report-templates/new`)
- [x] 11.2 Build blueprint card components (name, description, icon, "Use Blueprint" button)
- [x] 11.3 Implement blueprint-guided setup wizard (highlight user-configurable fields, step-by-step flow)
- [x] 11.4 Implement "Skip to Editor" option to bypass wizard
- [x] 11.5 Connect blueprint selection to editor pre-fill (load blueprint DSL into editor state)

## 12. Version Traceability Updates

- [x] 12.1 Add marketplace source badge to template detail page ("Installed from marketplace" + link)
- [x] 12.2 Add "Update available" badge when upstream marketplace template has newer version
- [x] 12.3 Update run detail page to show marketplace badge for runs from marketplace-installed templates
- [x] 12.4 Add `marketplace_source` field to template metadata schema and repository

## 13. Integration Testing & Polish

- [x] 13.1 Write E2E tests for blueprint → editor → publish → marketplace → install flow
- [x] 13.2 Write E2E tests for editor form step drag-and-drop and validation
- [x] 13.3 Write E2E tests for marketplace search, filter, and install
- [x] 13.4 Add loading states and error boundaries to all new pages
- [x] 13.5 Add translation keys to existing i18n locales (en-US + zh-CN) using the `core/i18n/` system for all new UI text
- [x] 13.6 Update CLAUDE.md with new modules, routes, and API endpoints
