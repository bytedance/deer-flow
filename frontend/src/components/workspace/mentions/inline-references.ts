import type { ConversationReference } from "@/core/conversation-references";
import {
  extensionMentionId,
  parseExtensionMention,
} from "@/core/extensions/mentions";

export const MAX_EXPLICIT_SKILLS = 16;

export type InlineReference = {
  kind: "skill" | "file" | "conversation" | "extension";
  id: string;
  label: string;
  start: number;
  end: number;
};

const pattern =
  /@\[([^\]]*)\]\(ref:(skill|file|conversation|extension):([^)]*)\)/g;

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

/** Restore display labels in one pass so replacement tokens cannot match again. */
export function restoreReferenceLabels(original: string, rewritten: string) {
  const remaining = inlineReferences(original);
  if (!remaining.length) return rewritten;
  const labels = [...new Set(remaining.map((ref) => ref.label))]
    .sort((a, b) => b.length - a.length)
    .map((label) => label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  // Longest labels win; a short label cannot consume a longer word or slug.
  const pattern = new RegExp(
    `@(?:${labels.join("|")})(?![\\p{L}\\p{M}\\p{N}_-])`,
    "gu",
  );
  const restored = rewritten.replace(pattern, (label) => {
    const index = remaining.findIndex((ref) => `@${ref.label}` === label);
    if (index < 0) return label;
    const [ref] = remaining.splice(index, 1);
    return referenceToken(ref!.kind, ref!.id, ref!.label);
  });
  // A rewrite may omit a label; retain that explicit selection in draft order.
  return [
    ...remaining.map((ref) => referenceToken(ref.kind, ref.id, ref.label)),
    restored,
  ].join(" ");
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

/** Select the adjacent object so native deletion also retains browser undo. */
export function selectReferenceForDeletion(
  root: HTMLElement,
  key: "Backspace" | "Delete",
): boolean {
  const caret = referenceCaret(root);
  if (caret === null) return false;
  for (const token of root.querySelectorAll<HTMLElement>("[data-reference]")) {
    const before = document.createRange();
    before.selectNodeContents(root);
    before.setEndBefore(token);
    const start = readReferenceEditor(before.cloneContents()).length;
    const boundary =
      key === "Backspace" ? start + token.dataset.reference!.length : start;
    if (caret !== boundary) continue;
    const range = document.createRange();
    range.selectNode(token);
    const selection = window.getSelection();
    selection?.removeAllRanges();
    selection?.addRange(range);
    return true;
  }
  return false;
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
          : ref.kind === "extension"
            ? "extension-mention-chip"
            : "inline-skill-reference";
    token.className =
      "inline-flex items-baseline gap-1 align-baseline font-medium select-all " +
      (ref.kind === "skill"
        ? "text-blue-600 dark:text-blue-400"
        : ref.kind === "file"
          ? "text-rose-600 dark:text-rose-400"
          : ref.kind === "extension"
            ? "text-teal-600 dark:text-teal-400"
            : "text-violet-600 dark:text-violet-400");
    const icon = document.createElement("span");
    icon.setAttribute("aria-hidden", "true");
    icon.textContent =
      ref.kind === "skill"
        ? "✦"
        : ref.kind === "file"
          ? "▤"
          : ref.kind === "extension"
            ? "◈"
            : "◉";
    token.append(icon, document.createTextNode(ref.label));
    token.setAttribute("aria-label", `@${ref.label}`);
    fragment.append(token);
    end = ref.end;
  }
  fragment.append(document.createTextNode(text.slice(end)));
  root.replaceChildren(fragment);
  if (caret !== null) focusReferenceAt(root, Math.min(caret, text.length));
}

export function reconcileConversationReferences(
  text: string,
  known: ConversationReference[],
  capability: {
    enabled: boolean;
    maxReferences: number;
    isLoading: boolean;
    isSuccess: boolean;
  },
  threadId: string,
): { text: string; references: ConversationReference[] } {
  // Only a successful discovery may destructively normalize the draft.
  // Preserve known metadata while pending/failed, including across editor changes.
  if (!capability.isSuccess || capability.isLoading) {
    const ids = new Set(
      inlineReferences(text)
        .filter((ref) => ref.kind === "conversation")
        .map((ref) => ref.id),
    );
    return { text, references: known.filter((ref) => ids.has(ref.threadId)) };
  }
  const references = new Map<string, ConversationReference>();
  const limit = capability.enabled ? capability.maxReferences : 0;
  const tokens = inlineReferences(text).filter(
    (ref) => ref.kind === "conversation",
  );
  for (const ref of tokens) {
    if (
      !ref.id ||
      ref.id === threadId ||
      references.has(ref.id) ||
      references.size >= limit
    )
      continue;
    references.set(
      ref.id,
      known.find((item) => item.threadId === ref.id) ?? {
        threadId: ref.id,
        title: ref.label,
      },
    );
  }
  // Disabled, self, and over-limit references become honest ordinary text.
  for (const ref of tokens.reverse()) {
    if (!references.has(ref.id))
      text = text.slice(0, ref.start) + `@${ref.label}` + text.slice(ref.end);
  }
  return { text, references: [...references.values()] };
}

/** Only references still present in the draft are submitted. */
export function extensionMentionMetadata(text: string) {
  const references = new Map<
    string,
    NonNullable<ReturnType<typeof parseExtensionMention>>
  >();
  for (const ref of inlineReferences(text)) {
    if (ref.kind !== "extension") continue;
    const mention = parseExtensionMention(ref.id, ref.label);
    if (mention) references.set(extensionMentionId(mention), mention);
  }
  return references.size
    ? { extension_mentions: [...references.values()] }
    : {};
}
