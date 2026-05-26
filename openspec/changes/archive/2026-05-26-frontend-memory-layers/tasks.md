# Tasks

## 1. Memory Editing API — Core Endpoints

- [x] 1.1 Create `MemoryAuditRow` ORM model in `backend/packages/harness/deerflow/persistence/orm/memory_audit.py`
- [x] 1.2 Add database migration for `memory_audit` table
- [x] 1.3 Create FastAPI router for memory endpoints in `backend/packages/harness/deerflow/api/memory.py`
- [x] 1.4 Implement `GET /api/v1/memory/{layer}` endpoint with filtering (confidence, date range, keyword)
- [x] 1.5 Implement `POST /api/v1/memory/{layer}/facts` endpoint with validation
- [x] 1.6 Implement `GET /api/v1/memory/{layer}/facts/{id}` endpoint
- [x] 1.7 Implement `PUT /api/v1/memory/{layer}/facts/{id}` endpoint with audit logging
- [x] 1.8 Implement `DELETE /api/v1/memory/{layer}/facts/{id}` endpoint with audit logging
- [x] 1.9 Add authentication and authorization middleware (user can edit own memory, admin can edit any)
- [x] 1.10 Write unit tests for all CRUD endpoints (success, validation errors, auth errors, tenant isolation)

## 2. Memory Export/Import API

- [x] 2.1 Implement `GET /api/v1/memory/{layer}/export` endpoint returning JSON file
- [x] 2.2 Implement `POST /api/v1/memory/{layer}/import` endpoint with schema validation
- [x] 2.3 Add JSON schema validation for import payload (version, facts array, metadata)
- [x] 2.4 Write unit tests for export/import (valid data, invalid schema, tenant isolation)

## 3. Audit Logging

- [x] 3.1 Create `log_memory_audit()` function to persist audit entries
- [x] 3.2 Integrate audit logging into all memory CRUD endpoints
- [x] 3.3 Implement `GET /api/v1/memory/audit` endpoint (admin only) with filtering (user_id, action, date range)
- [x] 3.4 Write unit tests for audit logging (create, update, delete actions, admin query)

## 4. WebSocket Event Emission

- [x] 4.1 Create `emit_memory_update()` function to send WebSocket events
- [x] 4.2 Integrate WebSocket emission into memory CRUD endpoints (after successful operation)
- [x] 4.3 Integrate WebSocket emission into agent memory updates (MemoryMiddleware)
- [x] 4.4 Ensure WebSocket events are tenant-scoped (only same-tenant connections receive events)
- [x] 4.5 Write unit tests for WebSocket events (event format, tenant isolation)

## 5. Frontend — Memory Panel Components

- [x] 5.1 Create `MemoryPanel` React component with tabs for User/Session/Domain Memory
- [x] 5.2 Create `MemoryFactCard` component displaying fact content and metadata (confidence, date, source, decay status)
- [x] 5.3 Create `MemorySearchBar` component with keyword search and filter controls (confidence, date range, domain/entity)
- [x] 5.4 Create `MemoryEditor` modal component for creating/editing facts
- [x] 5.5 Create `MemoryExportImport` dialog component for export/import operations
- [x] 5.6 Add Tailwind styling for all memory components (consistent with DeerFlow design system)
- [x] 5.7 Write unit tests for React components (rendering, user interactions, state management)

## 6. Frontend — API Integration

- [x] 6.1 Create TanStack Query hooks for memory API calls (`useMemoryFacts`, `useCreateFact`, `useUpdateFact`, `useDeleteFact`)
- [x] 6.2 Create TanStack Query hooks for export/import (`useExportMemory`, `useImportMemory`)
- [x] 6.3 Integrate API hooks into MemoryPanel and MemoryEditor components
- [x] 6.4 Add loading states, error handling, and success notifications
- [x] 6.5 Write integration tests for API calls (success, errors, loading states)

## 7. Frontend — Real-Time Updates

- [x] 7.1 Subscribe to SSE `memory_updated` events in MemoryPanel
- [x] 7.2 Auto-refresh memory list when relevant events are received
- [x] 7.3 Display "New" badge on recently created facts
- [x] 7.4 Debounce SSE event handling (max 1 refresh per second)
- [x] 7.5 Write unit tests for SSE integration (event handling, debouncing, auto-refresh)

## 8. Frontend — Memory Panel Integration

- [x] 8.1 Add "Memory" icon/button to thread view (opens MemoryPanel for current thread)
- [x] 8.2 Add "Memory" section to Settings page (opens MemoryPanel with User Memory focus)
- [x] 8.3 Implement memory layer visibility toggles (show/hide User/Session/Domain sections)
- [x] 8.4 Add navigation from source thread link to thread view
- [x] 8.5 Write integration tests for panel integration (opening, closing, navigation)

## 9. Configuration

- [x] 9.1 Add `MemoryApiConfig` class with fields: `enabled`, `max_content_length`, `audit_log_retention_days`
- [x] 9.2 Integrate config into main `AppConfig` (add `memory_api` section)
- [x] 9.3 Add feature flags for memory API and UI (`memory_api.enabled`, `memory_ui.enabled`)
- [x] 9.4 Write unit tests for config (defaults, validation)

## 10. Documentation

- [x] 10.1 Create `docs/MEMORY_UI.md` explaining Memory Inspection UI features and usage
- [x] 10.2 Document REST API endpoints with request/response examples (OpenAPI spec)
- [x] 10.3 Document WebSocket event format and subscription
- [x] 10.4 Document audit log schema and query examples
- [x] 10.5 Update `config.example.yaml` with memory API section and feature flags

## 11. Integration Tests

- [x] 11.1 Write end-to-end test: create fact via API → verify visible in UI
- [x] 11.2 Write end-to-end test: edit fact in UI → verify updated in storage and audit log
- [x] 11.3 Write end-to-end test: delete fact via API → verify removed from UI and audit log
- [x] 11.4 Write end-to-end test: export memory → import corrected version → verify updated
- [x] 11.5 Write end-to-end test: agent extracts fact → WebSocket event → UI auto-refreshes
