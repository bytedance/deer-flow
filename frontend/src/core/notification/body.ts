/** Longest notification body, counted in code points. */
export const MAX_NOTIFICATION_BODY_CODE_POINTS = 200;

/** Ellipsis appended to a shortened notification body. */
const ELLIPSIS = "...";

/**
 * Body for a "finished in the background" notification.
 *
 * The text is bounded by code points rather than UTF-16 code units: a
 * `String.prototype.length` / `substring` cut can land between the two halves
 * of an astral character (an emoji) and leave a lone surrogate, which the
 * notification renders as U+FFFD. Summaries that fit the budget are returned
 * whole even when they contain astral characters.
 */
export function notificationBody(
  text: string | null | undefined,
  fallback = "Conversation finished",
): string {
  if (!text) {
    return fallback;
  }
  const characters = Array.from(text);
  return characters.length > MAX_NOTIFICATION_BODY_CODE_POINTS
    ? `${characters.slice(0, MAX_NOTIFICATION_BODY_CODE_POINTS).join("")}${ELLIPSIS}`
    : text;
}
