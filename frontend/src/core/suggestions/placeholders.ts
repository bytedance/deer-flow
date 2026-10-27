/**
 * Regex matching known suggestion template placeholders.
 *
 * These are the exact placeholder tokens used in suggestion prompt templates
 * defined in the i18n locale files (e.g., zh-CN.ts, en-US.ts).
 *
 * Update this pattern whenever new placeholder tokens are added to templates.
 */
export const SUGGESTION_TEMPLATE_PLACEHOLDER_PATTERN =
  /\[(?:主题|来源|topic|source)\]/i;

/**
 * Locates an unreplaced suggestion template placeholder in the given text.
 *
 * Returns the start/end character indices of the placeholder if found,
 * or `null` if the text contains no known placeholder tokens.
 */
export function findSuggestionTemplatePlaceholder(
  text: string,
): { start: number; end: number } | null {
  const match = SUGGESTION_TEMPLATE_PLACEHOLDER_PATTERN.exec(text);
  if (!match) {
    return null;
  }

  return {
    start: match.index,
    end: match.index + match[0].length,
  };
}
