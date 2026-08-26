# Model Selector Overflow Design

## Problem

Long selected-model display names can paint outside the model selector button in both the main chat composer and the sidecar composer.

## Root cause

Each selected-model trigger wraps `ModelSelectorName` in a `flex-col items-start` container. `items-start` prevents the name span from stretching across the container's horizontal cross axis. The span therefore keeps its content width, so its existing `truncate` styles never observe internal overflow.

## Design

Remove `items-start` from the two selected-model wrappers. The default flex cross-axis behavior stretches the name span to the wrapper width, allowing the existing shared `truncate` styles to render an ellipsis. Keep `text-left` for text alignment and leave the generated `ai-elements/model-selector.tsx` component unchanged.

## Verification

Add one source-level unit test covering both selected-model triggers. This is appropriate because happy-dom does not calculate layout widths; the regression is the presence of the specific flex alignment class that defeats truncation. Run the focused test, the complete frontend unit suite, and `pnpm check`.
