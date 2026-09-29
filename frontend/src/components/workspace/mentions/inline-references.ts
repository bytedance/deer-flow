export type InlineReference = {
  kind: "skill" | "file" | "conversation";
  id: string;
  label: string;
  start: number;
  end: number;
};

const pattern = /@\[([^\]]*)\]\(ref:(skill|file|conversation):([^)]*)\)/g;

export function referenceToken(
  kind: InlineReference["kind"],
  id: string,
  label: string,
) {
  const encode = (value: string) =>
    encodeURIComponent(value).replace(
      /[!'()*]/g,
      (char) => `%${char.charCodeAt(0).toString(16)}`,
    );
  return `@[${encode(label)}](ref:${kind}:${encode(id)})`;
}

export function inlineReferences(text: string): InlineReference[] {
  const result: InlineReference[] = [];
  for (const match of text.matchAll(pattern)) {
    try {
      result.push({
        kind: match[2] as InlineReference["kind"],
        id: decodeURIComponent(match[3]!),
        label: decodeURIComponent(match[1]!),
        start: match.index,
        end: match.index + match[0].length,
      });
    } catch {
      /* Malformed pasted text remains ordinary text. */
    }
  }
  return result;
}

export function readableReferences(text: string) {
  let value = text;
  for (const reference of inlineReferences(text).reverse()) {
    value =
      value.slice(0, reference.start) +
      `@${reference.label}` +
      value.slice(reference.end);
  }
  return value;
}

export function readReferenceEditor(node: Node): string {
  if (node.nodeType === Node.TEXT_NODE) return node.textContent ?? "";
  if (node instanceof HTMLElement) {
    if (node.dataset.reference) return node.dataset.reference;
    if (node.tagName === "BR") return "\n";
  }
  return Array.from(node.childNodes, readReferenceEditor).join("");
}

export function referenceCaret(root: HTMLElement): number | null {
  const selection = window.getSelection();
  if (!selection?.isCollapsed || !selection.rangeCount) return null;
  const range = selection.getRangeAt(0);
  if (!root.contains(range.endContainer)) return null;
  const before = range.cloneRange();
  before.selectNodeContents(root);
  before.setEnd(range.endContainer, range.endOffset);
  return readReferenceEditor(before.cloneContents()).length;
}

export function focusReferenceAt(root: HTMLElement, offset: number) {
  root.focus();
  const range = document.createRange();
  range.selectNodeContents(root);
  range.collapse(false);
  let remaining = offset;
  for (const node of root.childNodes) {
    const length = readReferenceEditor(node).length;
    if (remaining <= length) {
      if (node.nodeType === Node.TEXT_NODE) range.setStart(node, remaining);
      else if (remaining === 0) range.setStartBefore(node);
      else range.setStartAfter(node);
      range.collapse(true);
      break;
    }
    remaining -= length;
  }
  const selection = window.getSelection();
  selection?.removeAllRanges();
  selection?.addRange(range);
}

export function renderReferenceEditor(root: HTMLElement, text: string) {
  if (readReferenceEditor(root) === text) return;
  const caret = referenceCaret(root);
  const fragment = document.createDocumentFragment();
  let end = 0;
  for (const ref of inlineReferences(text)) {
    fragment.append(document.createTextNode(text.slice(end, ref.start)));
    const token = document.createElement("span");
    token.contentEditable = "false";
    token.dataset.reference = text.slice(ref.start, ref.end);
    token.dataset.referenceKind = ref.kind;
    token.dataset.testid =
      ref.kind === "file"
        ? "project-attachment-chip"
        : ref.kind === "conversation"
          ? "conversation-reference-chip"
          : "inline-skill-reference";
    token.className =
      "inline-flex items-baseline gap-1 align-baseline font-medium select-all " +
      (ref.kind === "skill"
        ? "text-blue-600 dark:text-blue-400"
        : ref.kind === "file"
          ? "text-rose-600 dark:text-rose-400"
          : "text-violet-600 dark:text-violet-400");
    const icon = document.createElement("span");
    icon.setAttribute("aria-hidden", "true");
    icon.textContent =
      ref.kind === "skill" ? "✦" : ref.kind === "file" ? "▤" : "◉";
    token.append(icon, document.createTextNode(ref.label));
    token.setAttribute("aria-label", `@${ref.label}`);
    fragment.append(token);
    end = ref.end;
  }
  fragment.append(document.createTextNode(text.slice(end)));
  root.replaceChildren(fragment);
  if (caret !== null) focusReferenceAt(root, Math.min(caret, text.length));
}
