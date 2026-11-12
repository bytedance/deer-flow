export type CodePointSlice = {
  text: string;
  codePointCount: number;
  truncated: boolean;
};

/**
 * Slice `value` to at most `maxLength` code points without materializing the
 * whole string as an array. The scan stops as soon as the budget is exceeded,
 * so a multi-megabyte value costs only the prefix it needs.
 */
export function sliceToCodePoints(
  value: string,
  maxLength: number,
): CodePointSlice {
  const limit = Number.isNaN(maxLength)
    ? 0
    : Math.max(0, Math.floor(maxLength));
  let end = 0;
  let count = 0;
  for (const character of value) {
    if (count === limit) {
      return {
        text: value.slice(0, end),
        codePointCount: count,
        truncated: true,
      };
    }
    end += character.length;
    count += 1;
  }
  return { text: value, codePointCount: count, truncated: false };
}

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
  const bounded = sliceToCodePoints(value, maxLength);
  if (!bounded.truncated) {
    return value;
  }
  if (ellipsis && maxLength > ellipsis.length) {
    return (
      sliceToCodePoints(value, maxLength - ellipsis.length).text + ellipsis
    );
  }
  return bounded.text;
}
