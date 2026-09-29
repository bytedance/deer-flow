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

export function removeMentionQuery(text: string, mention: MentionQuery) {
  return text.slice(0, mention.start) + text.slice(mention.end);
}

export function editableCaret(element: HTMLElement): number | null {
  const selection = window.getSelection();
  if (!selection?.isCollapsed || selection.rangeCount === 0) return null;
  const range = selection.getRangeAt(0);
  if (!element.contains(range.endContainer)) return null;
  const before = range.cloneRange();
  before.selectNodeContents(element);
  before.setEnd(range.endContainer, range.endOffset);
  return before.toString().length;
}

export function focusEditableAt(element: HTMLElement, offset: number) {
  element.focus();
  const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
  let node = walker.nextNode();
  let remaining = offset;
  const range = document.createRange();
  range.selectNodeContents(element);
  range.collapse(false);
  while (node) {
    const length = node.textContent?.length ?? 0;
    if (remaining <= length) {
      range.setStart(node, remaining);
      range.collapse(true);
      break;
    }
    remaining -= length;
    node = walker.nextNode();
  }
  const selection = window.getSelection();
  selection?.removeAllRanges();
  selection?.addRange(range);
}
