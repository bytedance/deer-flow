/**
 * Regex matching known suggestion template placeholders.
 *
 * These are the exact placeholder tokens used in suggestion prompt templates
 * defined in the i18n locale files (e.g., zh-CN.ts, en-US.ts).
 *
 * Update this pattern whenever new placeholder tokens are added to templates.
 */
const PLACEHOLDER_PATTERN = /\[(?:topic|source|主题|来源)\]/gi;

/**
 * Returns `true` if the given text contains an unreplaced suggestion template
 * placeholder such as `[topic]`, `[source]`, `[主题]`, or `[来源]`.
 *
 * Used at the submit boundary to block messages that still contain raw
 * placeholder tokens from being sent to the backend.
 */
export function hasUnreplacedPlaceholder(text: string): boolean {
  // Reset lastIndex to avoid stateful regex bugs when the `g` flag is set.
  // Without this, consecutive calls may return incorrect results because
  // RegExp.test() advances lastIndex past each match.
  PLACEHOLDER_PATTERN.lastIndex = 0;
  return PLACEHOLDER_PATTERN.test(text);
}
