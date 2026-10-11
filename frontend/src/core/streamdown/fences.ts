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

/**
 * Whether `line` closes the fenced block opened by `fence`.
 *
 * Stricter than a bare marker match: a closing fence may not carry an info
 * string, so ``` ```python ``` is content of an outer ``` fence rather than its
 * end. Every fence consumer has to apply this, otherwise the block ends early
 * and whatever follows — a leaked ``<project>`` block on the render path, real
 * user content on the export path — is treated as prose.
 */
export function isClosingFence(line: string, fence: string): boolean {
  const trimmedLine = line.trimEnd();
  const indentationLength = trimmedLine.length - trimmedLine.trimStart().length;
  const fenceMarker = trimmedLine.slice(indentationLength);
  const fenceChar = fence.charAt(0);

  if (indentationLength > 3 || !fenceMarker.startsWith(fenceChar)) {
    return false;
  }

  return (
    fenceMarker.length >= fence.length &&
    [...fenceMarker].every((char) => char === fenceChar)
  );
}
