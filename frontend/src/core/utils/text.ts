/**
 * Move a UTF-16 `unitIndex` cut position forward when it would split a
 * surrogate pair, so a progressively revealed string never holds a lone
 * surrogate (rendered as U+FFFD) while a typing or streaming animation
 * commits prefixes.
 *
 * `String.prototype.slice` cuts by code unit; an emoji outside the BMP
 * spans two units, and a prefix ending between them is corrupt for as long
 * as the animation holds it. Indices at or past either end are returned
 * unchanged.
 */
export function snapForwardToCodePoint(
  text: string,
  unitIndex: number,
): number {
  if (unitIndex <= 0 || unitIndex >= text.length) {
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
