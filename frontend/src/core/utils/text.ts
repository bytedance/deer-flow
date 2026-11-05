/**
 * Truncate `value` to at most `maxLength` code points.
 *
 * `String.prototype.length` and `slice` count UTF-16 code units, so a
 * unit-based cut can split a surrogate pair (the lone half renders as
 * U+FFFD) and can shorten a value that already fits a code-point budget —
 * the same seam `briefReason` in `core/scheduled-tasks/format.ts` counts by
 * code points for. A value that fits is returned unchanged.
 *
 * When truncating with an `ellipsis`, the marker takes the last
 * `ellipsis.length` code points of the budget; without one — or when the
 * budget cannot hold the marker — the result is a plain code-point cut.
 */
export function truncateToCodePoints(
  value: string,
  maxLength: number,
  ellipsis = "",
): string {
  const characters = Array.from(value);
  if (characters.length <= maxLength) {
    return value;
  }
  if (ellipsis && maxLength > ellipsis.length) {
    return characters.slice(0, maxLength - ellipsis.length).join("") + ellipsis;
  }
  return characters.slice(0, maxLength).join("");
}
