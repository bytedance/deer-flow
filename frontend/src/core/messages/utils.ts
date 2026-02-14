import type { AIMessage, Message } from "@langchain/langgraph-sdk";

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

type MessageGroup =
  | HumanMessageGroup
  | AssistantProcessingGroup
  | AssistantMessageGroup
  | AssistantPresentFilesGroup
  | AssistantClarificationGroup
  | AssistantSubagentGroup;

export function groupMessages<T>(
  messages: Message[],
  mapper: (group: MessageGroup) => T,
): T[] {
  if (messages.length === 0) {
    return [];
  }
  const groups: MessageGroup[] = [];

  for (const message of messages) {
    const lastGroup = groups[groups.length - 1];
    if (message.type === "human") {
      groups.push({
        id: message.id,
        type: "human",
        messages: [message],
      });
    } else if (message.type === "tool") {
      // Check if this is a clarification tool message
      if (isClarificationToolMessage(message)) {
        // Add to processing group if available (to maintain tool call association)
        if (
          lastGroup &&
          lastGroup.type !== "human" &&
          lastGroup.type !== "assistant" &&
          lastGroup.type !== "assistant:clarification"
        ) {
          lastGroup.messages.push(message);
        }
        // Also create a separate clarification group for prominent display
        groups.push({
          id: message.id,
          type: "assistant:clarification",
          messages: [message],
        });
      } else if (
        lastGroup &&
        lastGroup.type !== "human" &&
        lastGroup.type !== "assistant" &&
        lastGroup.type !== "assistant:clarification"
      ) {
        lastGroup.messages.push(message);
      } else {
        throw new Error(
          "Tool message must be matched with a previous assistant message with tool calls",
        );
      }
    } else if (message.type === "ai") {
      if (hasReasoning(message) || hasToolCalls(message)) {
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
        } else {
          if (lastGroup?.type !== "assistant:processing") {
            groups.push({
              id: message.id,
              type: "assistant:processing",
              messages: [],
            });
          }
          const currentGroup = groups[groups.length - 1];
          if (currentGroup?.type === "assistant:processing") {
            currentGroup.messages.push(message);
          } else {
            throw new Error(
              "Assistant message with reasoning or tool calls must be preceded by a processing group",
            );
          }
        }
      }
      if (hasContent(message) && !hasToolCalls(message)) {
        groups.push({
          id: message.id,
          type: "assistant",
          messages: [message],
        });
      }
    }
  }

  const resultsOfGroups: T[] = [];
  for (const group of groups) {
    const resultOfGroup = mapper(group);
    if (resultOfGroup !== undefined && resultOfGroup !== null) {
      resultsOfGroups.push(resultOfGroup);
    }
  }
  return resultsOfGroups;
}

export function extractTextFromMessage(message: Message) {
  if (typeof message.content === "string") {
    return message.content.trim();
  }
  if (Array.isArray(message.content)) {
    return message.content
      .map((content) => (content.type === "text" ? content.text : ""))
      .join("\n")
      .trim();
  }
  return "";
}

export function extractContentFromMessage(message: Message) {
  if (typeof message.content === "string") {
    return message.content.trim();
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
  if (message.type !== "ai" || !message.additional_kwargs) {
    return null;
  }
  if ("reasoning_content" in message.additional_kwargs) {
    return message.additional_kwargs.reasoning_content as string | null;
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
    return message.content.trim().length > 0;
  }
  if (Array.isArray(message.content)) {
    return message.content.length > 0;
  }
  return false;
}

export function hasReasoning(message: Message) {
  return (
    message.type === "ai" &&
    typeof message.additional_kwargs?.reasoning_content === "string"
  );
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

/**
 * Represents an uploaded file parsed from the <uploaded_files> tag
 */
export interface UploadedFile {
  filename: string;
  size: string;
  path: string;
}

/**
 * Result of parsing uploaded files from message content
 */
export interface ParsedUploadedFiles {
  files: UploadedFile[];
  cleanContent: string;
}

/**
 * Parse <uploaded_files> tag from message content and extract file information.
 * Returns the list of uploaded files and the content with the tag removed.
 */
export function parseUploadedFiles(content: string): ParsedUploadedFiles {
  // Match <uploaded_files>...</uploaded_files> tag
  const uploadedFilesRegex = /<uploaded_files>([\s\S]*?)<\/uploaded_files>/;
  // eslint-disable-next-line @typescript-eslint/prefer-regexp-exec
  const match = content.match(uploadedFilesRegex);

  if (!match) {
    return { files: [], cleanContent: content };
  }

  const uploadedFilesContent = match[1];
  const cleanContent = content.replace(uploadedFilesRegex, "").trim();

  // Check if it's "No files have been uploaded yet."
  if (uploadedFilesContent?.includes("No files have been uploaded yet.")) {
    return { files: [], cleanContent };
  }

  // Parse file list
  // Format: - filename (size)\n  Path: /path/to/file
  const fileRegex = /- ([^\n(]+)\s*\(([^)]+)\)\s*\n\s*Path:\s*([^\n]+)/g;
  const files: UploadedFile[] = [];
  let fileMatch;

  while ((fileMatch = fileRegex.exec(uploadedFilesContent ?? "")) !== null) {
    files.push({
      filename: fileMatch[1].trim(),
      size: fileMatch[2].trim(),
      path: fileMatch[3].trim(),
    });
  }

  return { files, cleanContent };
}
