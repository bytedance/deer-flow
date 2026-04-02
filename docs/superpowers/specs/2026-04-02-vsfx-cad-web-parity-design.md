# VSFX cad-web parity design for DeerFlow

## Goal

Document the approved design for bringing DeerFlow's VSFX artifact experience up to cad-web parity for the core 3D viewer workflow.

The target scope is intentionally limited to:

- 3D mouse and wheel interaction
- active dragger switching from the toolbar
- selection, visibility, zoom, explode, cut-plane, regenerate, and reset commands
- stable synchronization between the viewer, construct tree, and properties panel

The design explicitly excludes:

- markup mode and markup toolbars
- preview and update-preview flows
- viewpoints, shared-link behavior, and cad-web page-level viewer chrome

## Current-state findings

- DeerFlow already has a VSFX artifact shell in `frontend/src/components/workspace/artifacts/vsfx/`.
- DeerFlow already renders a main VSFX panel plus floating construct tree and properties windows.
- DeerFlow already exposes most desired toolbar commands in `VsfxToolbar`, but the runtime beneath those controls is still incomplete.
- The current `frontend/src/lib/vsfx-viewer/runtime` layer is a lightweight wrapper, not a full interaction runtime.
- Mouse interaction is currently broken because the runtime does not yet implement cad-web's full input path:
  - no complete canvas DOM event binding in `Viewer.initialize()`
  - no persistent active dragger lifecycle
  - no dragger event subscription model
  - several draggers and actions are still placeholders that only call `update()`
- cad-web already contains the complete interaction model we want to match for this scope.

## Approved approach

The approved approach is to reuse DeerFlow's current artifact shell and data-loading flow, while upgrading `frontend/src/lib/vsfx-viewer` into a cad-web-grade runtime.

This keeps DeerFlow's current artifact UX and avoids importing cad-web's whole page-level viewer app. DeerFlow remains responsible for:

- artifact selection and loading
- sibling metadata pairing
- floating window layout
- context state consumed by DeerFlow UI

The upgraded VSFX runtime becomes responsible for:

- canvas event capture and forwarding
- dragger lifecycle and interaction behavior
- VisualizeJS command execution
- emitting normalized viewer events back into DeerFlow

## Architecture

### Shell boundary

The following DeerFlow-owned files remain the host shell:

- `frontend/src/components/workspace/artifacts/vsfx/VsfxArtifactViewer.tsx`
- `frontend/src/components/workspace/artifacts/vsfx/context.tsx`
- construct tree and properties floating windows
- DeerFlow artifact adapter and sibling metadata loading

The shell continues to mount the viewer, fetch `.vsfx` and sibling metadata artifacts, and render the DeerFlow-specific panel layout.

### Runtime boundary

The following area becomes the cad-web-aligned runtime:

- `frontend/src/lib/vsfx-viewer/viewer-core`
- `frontend/src/lib/vsfx-viewer/runtime`
- `frontend/src/lib/vsfx-viewer/components/VisualizeViewer.tsx`

This runtime is upgraded to support:

- full canvas input event wiring
- active dragger creation, initialization, disposal, and switching
- real orbit, pan, zoom, walk, measure, and cut-plane behavior
- viewer event emission compatible with DeerFlow context consumers

### Toolbar boundary

`frontend/src/components/workspace/artifacts/vsfx/VsfxToolbar.tsx` remains DeerFlow-owned and keeps DeerFlow styling, but its state and enablement rules become viewer-driven instead of locally inferred.

The toolbar should feel native to DeerFlow while matching cad-web's capability set for the scoped viewer workflow.

## Module design

### 1. Viewer core

Primary files:

- `frontend/src/lib/vsfx-viewer/runtime/Viewer.ts`
- `frontend/src/lib/vsfx-viewer/viewer-core/viewer/IViewer.ts`
- `frontend/src/lib/vsfx-viewer/viewer-core/viewer/ViewerEvents.ts`
- `frontend/src/lib/vsfx-viewer/viewer-core/viewer/CanvasEvents.ts`

Required changes:

- Bind the full canvas DOM event set during initialization, following the cad-web pattern.
- Set `touchAction` on the canvas and its parent to avoid browser gesture interference.
- Extend the viewer event model so draggers can subscribe to canvas input events and unsubscribe cleanly.
- Keep a persistent active dragger instance on the viewer instead of creating a temporary dragger during `setActiveDragger()`.
- On dragger switches, dispose the previous dragger, initialize the next dragger, emit `changeactivedragger`, and trigger a viewer update.
- Preserve the existing DeerFlow-friendly command and event APIs where possible so the outer shell does not need to know about VisualizeJS internals.

### 2. Draggers and action classes

Primary files:

- `frontend/src/lib/vsfx-viewer/runtime/Draggers/Common/OdBaseDragger.ts`
- `frontend/src/lib/vsfx-viewer/runtime/Draggers/OdOrbitPanDragger.ts`
- `frontend/src/lib/vsfx-viewer/runtime/Draggers/OdOrbitDragger.ts`
- `frontend/src/lib/vsfx-viewer/runtime/Draggers/OdPanDragger.ts`
- `frontend/src/lib/vsfx-viewer/runtime/Draggers/OdZoomDragger.ts`
- `frontend/src/lib/vsfx-viewer/runtime/Draggers/OdZoomWheelDragger.ts`
- `frontend/src/lib/vsfx-viewer/runtime/Draggers/WalkDragger.ts`
- `frontend/src/lib/vsfx-viewer/runtime/Draggers/Common/GestureManager.ts`
- `frontend/src/lib/vsfx-viewer/runtime/Draggers/Actions/*`

Required changes:

- Port cad-web's dragger lifecycle pattern so each dragger subscribes only to the canvas events it actually handles.
- Implement base pointer and mouse handling in `OdBaseDragger`, including pointer capture, drag start/move/end, click selection, and double-click zoom behavior where applicable.
- Implement real orbit, pan, zoom, and walk actions against the VisualizeJS viewer instead of placeholder `update()` calls.
- Keep `zoom-wheel` available as an always-on component, as in cad-web, without preventing the active dragger from handling its own pointer input.
- Keep gesture support aligned with cad-web's current runtime structure so touch and multi-pointer support can be extended later without redesigning the event model.

### 3. Commands

Primary files:

- `frontend/src/lib/vsfx-viewer/runtime/Commands/*`

Required command coverage for this scope:

- dragger switching
- `zoomToSelected`
- `zoomToExtents`
- `hideSelected`
- `isolateSelected`
- `showAll`
- `clearSelected`
- `planeViewX`, `planeViewY`, `planeViewZ`
- `clearSlices`
- `explode`
- `collect`
- `regenerateAll`
- `resetView`
- 3D view shortcuts
- `measureLine`

Commands remain the stable interface consumed by DeerFlow context actions and the toolbar. The outer DeerFlow layer should not call raw VisualizeJS APIs directly.

### 4. Toolbar

Primary files:

- `frontend/src/components/workspace/artifacts/vsfx/VsfxToolbar.tsx`
- `frontend/src/components/workspace/artifacts/vsfx/vsfx-toolbar-config.ts`

Required behavior:

- Keep DeerFlow's compact toolbar layout and styling.
- Keep the current DeerFlow grouping model: navigation, views, cuts, selection, and model.
- Replace local toolbar state guesses with viewer/context-backed state.
- Highlight the current active dragger based on viewer events, not local optimistic state.
- Enable or disable toolbar actions based on real runtime state such as:
  - viewer readiness
  - geometry loaded
  - selection presence
  - current dragger mode
  - model capability such as 3D-only controls
- Add parity for explode state display if needed for the DeerFlow toolbar treatment, but do not import cad-web's exact dropdown UI unless it materially improves the DeerFlow experience.

## State and data flow

### Viewer to context

The upgraded viewer emits standardized events, and `VsfxContextProvider` remains the place that translates those events into DeerFlow UI state.

Context should subscribe to and manage:

- `initialize`
- `databasechunk`
- `geometryend`
- `geometryerror`
- `select`
- `clear`
- `changeactivedragger`
- `explode`
- `resize`
- `planeviewlabel`

### Context state

The current context state remains the primary UI state source for DeerFlow windows and toolbar consumers.

Additional state needed for parity:

- `activeDragger: string`
- `explodeIndex: number`
- `is3D: boolean`

These fields allow the toolbar and floating windows to reflect runtime state without querying the viewer ad hoc.

### UI consumers

UI components consume context only:

- toolbar reads enablement, active dragger, and selection state
- construct tree reads selected and hidden handles
- properties panel reads the primary selected handle and properties payload

### UI actions

UI actions continue to call context actions first. Context actions then decide whether to:

- call `viewer.executeCommand(...)`
- call `viewer.setActiveDragger(...)`
- update local state for no-viewer cases

This preserves DeerFlow's current testing and state-isolation benefits.

## Parity scope by feature

### Included

- Pan
- Orbit
- Orbit/Pan
- Zoom
- Zoom wheel
- Walk
- Measure line
- 3D standard views
- Cut-plane toggles and clear
- Zoom to extents
- Zoom to selected
- Isolate selected
- Hide selected
- Show all
- Clear selection
- Explode and collect
- Regenerate
- Reset
- Construct tree selection and visibility sync
- Properties sync for selected handle

### Excluded

- Markup draggers and markup toolbars
- Markup color, width, line type, and font controls
- Preview generation
- Viewpoints and save-viewpoint flows
- Shared-link-specific viewer states
- cad-web's page-level header and contributes window system

## Implementation phases

### Phase 1: restore the input pipeline

Deliverables:

- full canvas event binding
- viewer event bus capable of carrying input events
- persistent active dragger lifecycle
- working `orbit-pan`, `orbit`, `pan`, `zoom`, and `zoom-wheel`

Exit criteria:

- viewer accepts mouse input
- wheel zoom works
- switching draggers from the toolbar changes behavior

### Phase 2: restore command parity for the scoped toolbar

Deliverables:

- scoped command set implemented against the real viewer backend
- toolbar driven by runtime state
- command availability based on readiness, selection, and geometry state

Exit criteria:

- every currently exposed DeerFlow VSFX toolbar control performs the expected viewer action

### Phase 3: stabilize DeerFlow panel synchronization

Deliverables:

- tree-to-viewer selection sync
- viewer-to-tree selection sync
- hidden state synchronization
- properties panel updates from selected handle
- state recovery after reset, clear slices, and show all

Exit criteria:

- tree, properties, and viewer stay in sync during normal interaction flows

### Phase 4: regression and compatibility coverage

Deliverables:

- runtime unit tests
- artifact integration tests
- focused regressions for resize, fast artifact switching, and state cleanup

Exit criteria:

- no scoped viewer regressions in DeerFlow's VSFX artifact flow

## Testing strategy

### Runtime tests

Cover:

- viewer initialization and disposal
- canvas event registration and cleanup
- active dragger switching and disposal
- command delegation into the backend
- resize plus redraw behavior
- dragger-specific event handling for orbit, pan, zoom, and wheel

### Artifact integration tests

Cover:

- toolbar enablement and active-state rendering
- tree selection driving viewer selection
- viewer selection driving tree highlight
- properties updates for selected handles
- isolate, hide, show all, reset, and clear slices
- artifact switching without stale listeners or stale state leakage

### Core regressions

Must specifically verify:

- resize does not break rendering or later input
- active dragger persists across normal interaction
- switching artifacts tears down old listeners
- geometry or metadata failures stay scoped to their own surfaces
- viewer controls remain usable after model reload

## Risks

- The biggest risk is not UI styling but interface mismatch between DeerFlow's simplified viewer runtime and cad-web's richer dragger/event model.
- Porting dragger behavior before the viewer event bus is aligned would create brittle fixes and duplicate logic.
- Some cad-web actions depend on helper methods or VisualizeJS assumptions that DeerFlow's current runtime stubs do not yet expose.
- Explode and walk behavior may require a small amount of DeerFlow-specific presentation logic even when the underlying viewer command is ported directly.

## Out-of-scope follow-up work

Once this scoped parity work is complete, future specs can cover:

- markup mode
- preview workflows
- viewpoints
- broader contributed windows or tool dropdown parity

Those concerns are intentionally excluded from this design so the current work can focus on making the DeerFlow VSFX artifact viewer function correctly and predictably for core 3D inspection tasks.
