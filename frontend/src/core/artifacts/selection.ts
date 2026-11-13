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

// Rendered Markdown can omit markup or repeat the same words. Only an exact,
// unique occurrence within the selected source blocks is safe to replace.
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
  const startLine = source.slice(0, from).split("\n").length;
  const last = source[to - 1] === "\n" ? to - 1 : to;
  return { startLine, endLine: source.slice(0, last).split("\n").length };
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
  range: SourceSelection,
): SidecarContext {
  const { startLine, endLine } = selectionLines(source, range.from, range.to);
  return {
    type: "referenced_message",
    role: "assistant",
    label: `${filepath}:L${startLine}-L${endLine}`,
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
