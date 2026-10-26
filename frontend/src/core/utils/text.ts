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

/**
 * Move a UTF-16 `unitIndex` cut position forward when it would split a
 * surrogate pair, so a progressively revealed string never holds a lone
 * surrogate (rendered as U+FFFD) while a typing or streaming animation
 * commits prefixes.
 *
 * `String.prototype.slice` cuts by code unit; an emoji outside the BMP
 * spans two units, and a prefix ending between them is corrupt for as long
 * as the animation holds it. If a streaming chunk currently ends with a lone
 * high surrogate, a cut at that end is held before it until the matching low
 * surrogate arrives. Indices beyond either end are returned unchanged.
 */
export function snapForwardToCodePoint(
  text: string,
  unitIndex: number,
): number {
  if (unitIndex <= 0) {
    return unitIndex;
  }
  if (unitIndex >= text.length) {
    if (unitIndex === text.length && text.length > 0) {
      const last = text.charCodeAt(text.length - 1);
      const endsWithHighSurrogate = last >= 0xd800 && last <= 0xdbff;
      if (endsWithHighSurrogate) {
        return text.length - 1;
      }
    }
    return unitIndex;
  }
  const previous = text.charCodeAt(unitIndex - 1);
  const current = text.charCodeAt(unitIndex);
  const splitsSurrogatePair =
    previous >= 0xd800 &&
    previous <= 0xdbff &&
    current >= 0xdc00 &&
    current <= 0xdfff;
  return splitsSurrogatePair ? unitIndex + 1 : unitIndex;
}
