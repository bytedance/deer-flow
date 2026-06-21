import type { AIMessage, Message } from "@langchain/langgraph-sdk";

import type { UploadStatus } from "../models/status";

interface GenericMessageGroup<T = string> {
  type: T;
  id: string | undefined;
  messages: Message[];
}

interface HumanMessageGroup extends GenericMessageGroup<"human"> {}

interface AssistantProcessingGroup extends GenericMessageGroup<"assistant:processing"> {}

interface AssistantMessageGroup extends GenericMessageGroup<"assistant"> {}

interface AssistantPresentFilesGroup extends GenericMessageGroup<"assistant:present-files"> {}

interface AssistantClarificationGroup extends GenericMessageGroup<"assistant:clarification"> {}

interface AssistantSubagentGroup extends GenericMessageGroup<"assistant:subagent"> {}

export type MessageGroup =
  | HumanMessageGroup
  | AssistantProcessingGroup
  | AssistantMessageGroup
  | AssistantPresentFilesGroup
  | AssistantClarificationGroup
  | AssistantSubagentGroup;

export function getMessageGroups(messages: Message[], isLoading?: boolean): MessageGroup[] {
  if (messages.length === 0) {
    return [];
  }

  const groups: MessageGroup[] = [];

  // Returns the last group if it can still accept tool messages
  // (i.e. it's an in-flight processing group, not a terminal human/assistant group).
  function lastOpenGroup() {
    const last = groups[groups.length - 1];
    if (
      last &&
      last.type !== "human" &&
      last.type !== "assistant" &&
      last.type !== "assistant:clarification"
    ) {
      return last;
    }
    return null;
  }

  for (const message of messages) {
    if (isHiddenFromUIMessage(message, isLoading)) {
      continue;
    }

    if (message.name === "todo_reminder") {
      continue;
    }

    if (message.type === "human") {
      groups.push({ id: message.id, type: "human", messages: [message] });
      continue;
    }

    if (message.type === "tool") {
      if (isClarificationToolMessage(message)) {
        // Add to the preceding processing group to preserve tool-call association,
        // then also open a standalone clarification group for prominent display.
        lastOpenGroup()?.messages.push(message);
        groups.push({
          id: message.id,
          type: "assistant:clarification",
          messages: [message],
        });
      } else {
        const open = lastOpenGroup();
        if (open) {
          open.messages.push(message);
        } else if (message.name || message.tool_call_id) {
          // Tool message arrived without an open processing group — likely due to
          // out-of-order streaming or the preceding AI message being classified as
          // a terminal group. Create a synthetic processing group to preserve it.
          groups.push({
            id: message.id,
            type: "assistant:processing",
            messages: [message],
          });
        }
      }
      continue;
    }

    if (message.type === "ai") {
      if (hasPresentFiles(message)) {
        groups.push({
          id: message.id,
          type: "assistant:present-files",
          messages: [message],
        });
      } else if (hasSubagent(message)) {
        groups.push({
          id: message.id,
          type: "assistant:subagent",
          messages: [message],
        });
      } else if (hasReasoning(message) || hasToolCalls(message)) {
        const lastGroup = groups[groups.length - 1];
        // Accumulate consecutive intermediate AI messages into one processing group.
        if (lastGroup?.type !== "assistant:processing") {
          groups.push({
            id: message.id,
            type: "assistant:processing",
            messages: [message],
          });
        } else {
          lastGroup.messages.push(message);
        }
      }

      // Not an else-if: a message with reasoning + content (but no tool calls) goes
      // into the processing group above AND gets its own assistant bubble here.
      if (hasContent(message) && !hasToolCalls(message)) {
        groups.push({ id: message.id, type: "assistant", messages: [message] });
      }
    }
  }

  return groups;
}

export function groupMessages<T>(
  messages: Message[],
  mapper: (group: MessageGroup) => T,
  isLoading?: boolean,
): T[] {
  return getMessageGroups(messages, isLoading)
    .map(mapper)
    .filter((result) => result !== undefined && result !== null) as T[];
}

function cloneGroups(groups: MessageGroup[]): MessageGroup[] {
  return groups.map((group) => ({
    ...group,
    messages: [...group.messages],
  }));
}

function isOpenGroupType(type: MessageGroup["type"]): boolean {
  return (
    type !== "human" &&
    type !== "assistant" &&
    type !== "assistant:clarification"
  );
}

export function extendMessageGroups(
  existingGroups: MessageGroup[],
  newMessages: Message[],
  isLoading?: boolean,
): MessageGroup[] {
  if (newMessages.length === 0) {
    return existingGroups;
  }
  if (existingGroups.length === 0) {
    return getMessageGroups(newMessages, isLoading);
  }

  const cloned = cloneGroups(existingGroups);

  for (const message of newMessages) {
    if (isHiddenFromUIMessage(message, isLoading)) {
      continue;
    }

    if (message.name === "todo_reminder") {
      continue;
    }

    if (message.type === "human") {
      cloned.push({ id: message.id, type: "human", messages: [message] });
      continue;
    }

    if (message.type === "tool") {
      const currentLast = cloned[cloned.length - 1];
      const currentOpen =
        currentLast !== undefined && isOpenGroupType(currentLast.type);

      if (isClarificationToolMessage(message)) {
        if (currentOpen && currentLast) {
          currentLast.messages.push(message);
        }
        cloned.push({
          id: message.id,
          type: "assistant:clarification",
          messages: [message],
        });
      } else {
        if (currentOpen && currentLast) {
          currentLast.messages.push(message);
        } else if (message.name || message.tool_call_id) {
          cloned.push({
            id: message.id,
            type: "assistant:processing",
            messages: [message],
          });
        }
      }
      continue;
    }

    if (message.type === "ai") {
      if (hasPresentFiles(message)) {
        cloned.push({
          id: message.id,
          type: "assistant:present-files",
          messages: [message],
        });
      } else if (hasSubagent(message)) {
        cloned.push({
          id: message.id,
          type: "assistant:subagent",
          messages: [message],
        });
      } else if (hasReasoning(message) || hasToolCalls(message)) {
        const last = cloned[cloned.length - 1];
        if (last?.type === "assistant:processing") {
          last.messages.push(message);
        } else {
          cloned.push({
            id: message.id,
            type: "assistant:processing",
            messages: [message],
          });
        }
      }

      if (hasContent(message) && !hasToolCalls(message)) {
        cloned.push({ id: message.id, type: "assistant", messages: [message] });
      }
    }
  }

  return cloned;
}

export function getAssistantTurnUsageMessages(groups: MessageGroup[]) {
  const usageMessagesByGroupIndex: Array<Message[] | null> = Array.from(
    { length: groups.length },
    () => null,
  );

  let turnStartIndex: number | null = null;

  for (const [index, group] of groups.entries()) {
    if (group.type === "human") {
      turnStartIndex = null;
      continue;
    }

    turnStartIndex ??= index;

    const nextGroup = groups[index + 1];
    const isTurnEnd = !nextGroup || nextGroup.type === "human";

    if (!isTurnEnd) {
      continue;
    }

    usageMessagesByGroupIndex[index] = groups
      .slice(turnStartIndex, index + 1)
      .flatMap((currentGroup) => currentGroup.messages)
      .filter((message) => message.type === "ai");

    turnStartIndex = null;
  }

  return usageMessagesByGroupIndex;
}

export function extractTextFromMessage(message: Message) {
  if (typeof message.content === "string") {
    return (
      splitInlineReasoningFromAIMessage(message)?.content ??
      message.content.trim()
    );
  }
  if (Array.isArray(message.content)) {
    return message.content
      .map((content) => (content.type === "text" ? content.text : ""))
      .join("\n")
      .trim();
  }
  return "";
}

const THINK_TAG_RE = /<think>\s*([\s\S]*?)\s*<\/think>/g;

function splitInlineReasoning(content: string) {
  const reasoningParts: string[] = [];
  const cleaned = content
    .replace(THINK_TAG_RE, (_, reasoning: string) => {
      const normalized = reasoning.trim();
      if (normalized) {
        reasoningParts.push(normalized);
      }
      return "";
    })
    .trim();

  return {
    content: cleaned,
    reasoning: reasoningParts.length > 0 ? reasoningParts.join("\n\n") : null,
  };
}

function splitInlineReasoningFromAIMessage(message: Message) {
  if (message.type !== "ai" || typeof message.content !== "string") {
    return null;
  }
  return splitInlineReasoning(message.content);
}

export function extractContentFromMessage(message: Message) {
  if (typeof message.content === "string") {
    return (
      splitInlineReasoningFromAIMessage(message)?.content ??
      message.content.trim()
    );
  }
  if (Array.isArray(message.content)) {
    return message.content
      .map((content) => {
        switch (content.type) {
          case "text":
            return content.text;
          case "image_url":
            const imageURL = extractURLFromImageURLContent(content.image_url);
            return `![image](${imageURL})`;
          default:
            return "";
        }
      })
      .join("\n")
      .trim();
  }
  return "";
}

export function extractReasoningContentFromMessage(message: Message) {
  if (message.type !== "ai") {
    return null;
  }
  if (
    message.additional_kwargs &&
    "reasoning_content" in message.additional_kwargs
  ) {
    return message.additional_kwargs.reasoning_content as string | null;
  }
  if (Array.isArray(message.content)) {
    const part = message.content[0];
    if (part && "thinking" in part) {
      return part.thinking as string;
    }
  }
  if (typeof message.content === "string") {
    return splitInlineReasoning(message.content).reasoning;
  }
  return null;
}

export function removeReasoningContentFromMessage(message: Message) {
  if (message.type !== "ai" || !message.additional_kwargs) {
    return;
  }
  delete message.additional_kwargs.reasoning_content;
}

export function extractURLFromImageURLContent(
  content:
    | string
    | {
        url: string;
      },
) {
  if (typeof content === "string") {
    return content;
  }
  return content.url;
}

export function hasContent(message: Message) {
  if (typeof message.content === "string") {
    return (
      (
        splitInlineReasoningFromAIMessage(message)?.content ??
        message.content.trim()
      ).length > 0
    );
  }
  if (Array.isArray(message.content)) {
    return message.content.length > 0;
  }
  return false;
}

export function hasReasoning(message: Message) {
  if (message.type !== "ai") {
    return false;
  }
  if (typeof message.additional_kwargs?.reasoning_content === "string") {
    return true;
  }
  if (Array.isArray(message.content)) {
    const part = message.content[0];
    // Compatible with the Anthropic gateway
    return (part as unknown as { type: "thinking" })?.type === "thinking";
  }
  if (typeof message.content === "string") {
    return splitInlineReasoning(message.content).reasoning !== null;
  }
  return false;
}

export function hasToolCalls(message: Message) {
  return (
    message.type === "ai" && message.tool_calls && message.tool_calls.length > 0
  );
}

export function hasPresentFiles(message: Message) {
  return (
    message.type === "ai" &&
    message.tool_calls?.some((toolCall) => toolCall.name === "present_files")
  );
}

export function isClarificationToolMessage(message: Message) {
  return message.type === "tool" && message.name === "ask_clarification";
}

export function extractPresentFilesFromMessage(message: Message) {
  if (message.type !== "ai" || !hasPresentFiles(message)) {
    return [];
  }
  const files: string[] = [];
  for (const toolCall of message.tool_calls ?? []) {
    if (
      toolCall.name === "present_files" &&
      Array.isArray(toolCall.args.filepaths)
    ) {
      files.push(...(toolCall.args.filepaths as string[]));
    }
  }
  return files;
}

export function hasSubagent(message: AIMessage) {
  for (const toolCall of message.tool_calls ?? []) {
    if (toolCall.name === "task") {
      return true;
    }
  }
  return false;
}

export function findToolCallResult(toolCallId: string, messages: Message[]) {
  for (const message of messages) {
    if (message.type === "tool" && message.tool_call_id === toolCallId) {
      const content = extractTextFromMessage(message);
      if (content) {
        return content;
      }
    }
  }
  return undefined;
}

export function isTransientMessageName(name?: string | null): boolean {
  const lower = (name ?? "").toLowerCase();
  return new Set(["summary", "intent", "agent_intent", "session_intent"]).has(lower);
}

export function isHiddenFromUIMessage(message: Message, isLoading?: boolean): boolean {
  // During streaming, show summary/intent so the user can see the agent's plan.
  // After streaming completes, hide them so the conversation is clean.
  const isTransient = isTransientMessageName(message.name);
  const hideTransient = isTransient && !isLoading;

  const text = extractTextFromMessage(message);
  const isInteractionPayload =
    typeof text === "string" && text.startsWith('{"type":"ui_interaction"');

  // Hide structured-summary text the model spontaneously generates
  // (## SESSION INTENT / ## SUMMARY / ## ARTIFACTS / ## NEXT STEPS).
  // It's pure process documentation, not a user-facing reply.
  const isStructuredSummary =
    typeof text === "string" &&
    /^\s*##\s+(SESSION\s+INTENT|SUMMARY|ARTIFACTS|NEXT\s+STEPS)\b/i.test(text);
  const isSafetyPolicyBlock =
    message.type === "human" &&
    typeof text === "string" &&
    /^\s*\[Content blocked by safety policy:[\s\S]*\]\s*$/.test(text);

  return (
    message.additional_kwargs?.hide_from_ui === true ||
    message.name === "loop_warning" ||
    hideTransient ||
    isInteractionPayload ||
    isStructuredSummary ||
    isSafetyPolicyBlock
  );
}

/**
 * Represents a file stored in message additional_kwargs.files.
 * Used for optimistic UI (uploading state) and structured file metadata.
 */
export interface FileInMessage {
  filename: string;
  size: number; // bytes
  path?: string; // virtual path, may not be set during upload
  status?: UploadStatus;
}

/**
 * Strip <uploaded_files> tag from message content.
 * Returns the content with the tag removed.
 */
export function stripUploadedFilesTag(content: string): string {
  return content
    .replace(/<uploaded_files>[\s\S]*?<\/uploaded_files>/g, "")
    .trim();
}

export function stripDeepLinkParams(content: string): string {
  return content
    .replace(/<deep_link_params>[\s\S]*?<\/deep_link_params>/g, "")
    .trim();
}

export function parseUploadedFiles(content: string): FileInMessage[] {
  // Match <uploaded_files>...</uploaded_files> tag
  const uploadedFilesRegex = /<uploaded_files>([\s\S]*?)<\/uploaded_files>/;
  // eslint-disable-next-line @typescript-eslint/prefer-regexp-exec
  const match = content.match(uploadedFilesRegex);

  if (!match) {
    return [];
  }

  const uploadedFilesContent = match[1];

  // Check if it's "No files have been uploaded yet."
  if (uploadedFilesContent?.includes("No files have been uploaded yet.")) {
    return [];
  }

  // Check if the backend reported no new files were uploaded in this message
  if (uploadedFilesContent?.includes("(empty)")) {
    return [];
  }

  // Parse file list
  // Format: - filename (size)\n  Path: /path/to/file
  const fileRegex = /- ([^\n(]+)\s*\(([^)]+)\)\s*\n\s*Path:\s*([^\n]+)/g;
  const files: FileInMessage[] = [];
  let fileMatch;

  while ((fileMatch = fileRegex.exec(uploadedFilesContent ?? "")) !== null) {
    files.push({
      filename: fileMatch[1].trim(),
      size: parseInt(fileMatch[2].trim(), 10) ?? 0,
      path: fileMatch[3].trim(),
    });
  }

  return files;
}

const RETRIEVAL_TRACE_RE =
  /<retrieval_trace>([\s\S]*?)<\/retrieval_trace>/;

export interface RetrievalSource {
  kb_id: string;
  kb_name: string;
  doc_title: string;
  score: number;
}

export function extractRetrievalTrace(
  messages: Message[],
): RetrievalSource[] | null {
  for (let i = messages.length - 1; i >= 0; i--) {
    const msg = messages[i];
    if (msg?.type !== "system" && msg?.type !== "ai") continue;
    const content =
      typeof msg.content === "string" ? msg.content : "";
    const match = RETRIEVAL_TRACE_RE.exec(content);
    if (!match?.[1]) continue;
    try {
      const parsed = JSON.parse(match[1]) as { sources?: RetrievalSource[] };
      if (parsed.sources && parsed.sources.length > 0) {
        return parsed.sources;
      }
    } catch {
      continue;
    }
  }
  return null;
}
