export type MentionQuery = { start: number; end: number; query: string };

/** Only a standalone @ at the caret opens the picker, never an email or URL. */
export function getMentionQuery(
  text: string,
  caret: number,
): MentionQuery | null {
  if (caret < 0 || caret > text.length) return null;
  const before = text.slice(0, caret);
  const match = /(?:^|[\s（(，,。:：])@([^\s@/\\]*)$/u.exec(before);
  if (!match) return null;
  const query = match[1] ?? "";
  return { start: caret - query.length - 1, end: caret, query };
}
