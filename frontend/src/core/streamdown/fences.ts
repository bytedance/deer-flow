/**
 * Fence and indented-code detection shared by the render path
 * (`streamdown/preprocess.ts`) and the export scrub
 * (`messages/utils.ts::stripInternalMarkers`). Kept dependency-free: both
 * consumers already depend on each other's module graph, so the regexes live
 * in a leaf module they can import without a cycle.
 */
export const INDENTED_CODE_RE = /^(?: {4}|\t)/;

// Marker-aware: tracks the opening character and run length, so a tilde fence
// containing a shorter backtick run (or a 4-backtick block containing a
// 3-backtick run) does not prematurely close the fence.
export const FENCE_MARKER_RE = /^ {0,3}(`{3,}|~{3,})/;
