import type { Message } from "@langchain/langgraph-sdk";

import { extractTextFromMessage } from "@/core/messages/utils";
import type { SidecarContext } from "@/core/sidecar";

import type { ArtifactDraftState } from "./editing";

export type SourceSelection = { from: number; to: number };
export type ArtifactSelectionEdit = {
  id: string;
  context: SidecarContext;
  filepath: string;
  threadId: string;
  ownerId?: string;
  source: string;
  revision: string;
} & SourceSelection;

export function applyArtifactSelectionDraft(
  draft: ArtifactDraftState | undefined,
  edit: ArtifactSelectionEdit,
  replacement: string,
) {
  if (
    draft?.filepath !== edit.filepath ||
    draft.conflict ||
    draft.baselineSha256 !== edit.revision ||
    draft.draftContent !== edit.source
  )
    return null;
  return {
    ...draft,
    draftContent: replaceArtifactSelection(
      draft.draftContent,
      edit,
      replacement,
    ),
  };
}

export const MAX_SELECTION_LENGTH = 12_000;
export const MAX_REPLACEMENT_LENGTH = 64_000;

// A unique text match can locate a quotation, but does not prove which
// Markdown source span produced the rendered text.
export function locateArtifactSelection(
  source: string,
  text: string,
  lower = 0,
  upper = source.length,
): SourceSelection | null {
  if (!text || lower < 0 || upper > source.length || lower >= upper)
    return null;
  const from = source.indexOf(text, lower);
  if (from < 0 || from + text.length > upper) return null;
  const duplicate = source.indexOf(text, from + 1);
  if (duplicate >= 0 && duplicate + text.length <= upper) return null;
  return { from, to: from + text.length };
}

export function selectionLines(source: string, from: number, to: number) {
  const lineBreak = /\r\n?|\n/;
  const startLine = source.slice(0, from).split(lineBreak).length;
  const endLine = source
    .slice(0, to)
    .replace(/(?:\r\n?|\n)$/, "")
    .split(lineBreak).length;
  return { startLine, endLine };
}

// CodeMirror represents each CRLF as one position. Shift each endpoint for
// the CRLFs it has already passed in the original source.
export function sourceSelectionOffsets(
  source: string,
  { from, to }: SourceSelection,
): SourceSelection {
  for (const match of source.matchAll(/\r\n/g)) {
    if (match.index >= to) break;
    if (match.index < from) from++;
    to++;
  }
  return { from, to };
}

export function replaceArtifactSelection(
  current: string,
  selection: SourceSelection & { source: string },
  replacement: string,
) {
  const { source, from, to } = selection;
  if (
    current !== source ||
    !Number.isInteger(from) ||
    !Number.isInteger(to) ||
    from < 0 ||
    from >= to ||
    to > source.length ||
    replacement.length > MAX_REPLACEMENT_LENGTH
  )
    throw new Error("The artifact selection has changed");
  return source.slice(0, from) + replacement + source.slice(to);
}

export function artifactSelectionContext(
  filepath: string,
  source: string,
  text: string,
  range: SourceSelection | null,
): SidecarContext {
  const lines = range && selectionLines(source, range.from, range.to);
  return {
    type: "referenced_message",
    role: "assistant",
    label: lines
      ? `${filepath}:L${lines.startLine}-L${lines.endLine}`
      : filepath,
    content: text,
  };
}

// An answer must follow a submitted request for this particular edit. Restored
// sidecar history and a previous edit's answer must never become replacements.
export function artifactReplacement(messages: Message[], editId: string) {
  const reversed = [...messages].reverse();
  const lastHumanReverse = reversed.findIndex(
    (message) =>
      message.type === "human" &&
      message.additional_kwargs?.sidecar_visible_message === true,
  );
  const lastHuman =
    lastHumanReverse < 0 ? -1 : messages.length - 1 - lastHumanReverse;
  if (
    lastHuman < 0 ||
    messages[lastHuman]?.additional_kwargs?.artifact_selection_edit !== editId
  )
    return null;
  const answer = messages
    .slice(lastHuman + 1)
    .reverse()
    .find(
      (message) =>
        message.type === "ai" &&
        !message.tool_calls?.length &&
        message.additional_kwargs?.hide_from_ui !== true &&
        extractTextFromMessage(message).trim(),
    );
  if (!answer) return null;
  const visible = extractTextFromMessage(answer);
  const raw =
    typeof answer.content === "string"
      ? answer.content
      : answer.content
          .flatMap((part) =>
            typeof part === "string"
              ? [part]
              : part.type === "text" && typeof part.text === "string"
                ? [part.text]
                : [],
          )
          .join("\n");
  // The message renderer trims display text and removes inline reasoning. Keep
  // code indentation when the visible answer is otherwise unchanged.
  const text = raw.trim() === visible ? raw : visible;
  // Accept a single wrapping code fence, preserving the replacement's internal
  // whitespace. Users can review and edit the text before applying it.
  const fenced = /^```[^\n]*\r?\n([\s\S]*?)\r?\n```$/.exec(text.trim());
  const replacement = fenced?.[1] ?? text;
  return replacement.length <= MAX_REPLACEMENT_LENGTH ? replacement : null;
}
