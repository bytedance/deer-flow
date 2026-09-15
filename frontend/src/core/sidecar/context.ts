import type { Message } from "@langchain/langgraph-sdk";

import {
  extractTextFromMessage,
  isHiddenFromUIMessage,
} from "@/core/messages/utils";

export type SidecarContextRole = "user" | "assistant";

export type ReferencedMessageSidecarContext = {
  type: "referenced_message";
  label: string;
  messageId?: string;
  role: SidecarContextRole;
  content: string;
};

export type SidecarContext = ReferencedMessageSidecarContext;

export type ParentConversationContextMessage = {
  messageId?: string;
  role: SidecarContextRole;
  content: string;
};

export function normalizeSidecarContexts(
  contextOrContexts: SidecarContext | SidecarContext[],
): SidecarContext[] {
  return Array.isArray(contextOrContexts)
    ? contextOrContexts
    : [contextOrContexts];
}

function roleOfMessage(message: Message): SidecarContextRole | null {
  if (message.type === "human") {
    return "user";
  }
  if (message.type === "ai") {
    return "assistant";
  }
  return null;
}

function labelOfRole(role: SidecarContextRole) {
  return role === "user" ? "User" : "Assistant";
}

function truncateContextText(content: string, maxChars: number) {
  if (content.length <= maxChars) {
    return content;
  }
  return `${content.slice(0, maxChars).trimEnd()}\n[truncated]`;
}

export function buildParentConversationContext(
  messages: Message[],
  {
    maxMessages = 8,
    maxCharsPerMessage = 1200,
    maxTotalChars = 6000,
  }: {
    maxMessages?: number;
    maxCharsPerMessage?: number;
    maxTotalChars?: number;
  } = {},
): ParentConversationContextMessage[] {
  const visibleMessages = messages.flatMap((message) => {
    const role = roleOfMessage(message);
    if (!role || isHiddenFromUIMessage(message)) {
      return [];
    }
    const content = extractTextFromMessage(message).trim();
    if (!content) {
      return [];
    }
    return [
      {
        messageId: message.id,
        role,
        content,
      },
    ];
  });

  const recentMessages = visibleMessages.slice(-maxMessages);
  const selectedMessages: ParentConversationContextMessage[] = [];
  let selectedChars = 0;

  for (let index = recentMessages.length - 1; index >= 0; index -= 1) {
    const message = recentMessages[index];
    if (!message) {
      continue;
    }
    const remainingChars = Math.max(maxTotalChars - selectedChars, 0);
    if (remainingChars <= 0) {
      break;
    }
    const content = truncateContextText(
      message.content,
      Math.min(maxCharsPerMessage, remainingChars),
    );
    selectedMessages.unshift({
      ...message,
      content,
    });
    selectedChars += content.length;
  }

  return selectedMessages;
}

export function buildMessageSidecarContext(
  message: Message,
  displayIndex?: number,
  {
    selectedText,
  }: {
    selectedText?: string;
  } = {},
): ReferencedMessageSidecarContext | null {
  const role = roleOfMessage(message);
  const content = selectedText?.trim() ?? extractTextFromMessage(message);
  if (!role || !content || isHiddenFromUIMessage(message)) {
    return null;
  }

  const prefix = selectedText
    ? role === "assistant"
      ? "Selected assistant text"
      : "Selected user text"
    : role === "assistant"
      ? "Assistant message"
      : "User message";
  return {
    type: "referenced_message",
    label:
      typeof displayIndex === "number" ? `${prefix} #${displayIndex}` : prefix,
    messageId: message.id,
    role,
    content,
  };
}

function escapeXmlAttribute(value: string) {
  return value
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

export function buildSidecarContextPrompt(
  contextOrContexts: SidecarContext | SidecarContext[] = [],
  {
    parentConversation = [],
  }: {
    parentConversation?: ParentConversationContextMessage[];
  } = {},
) {
  const contexts = normalizeSidecarContexts(contextOrContexts);
  const lines = [
    "You are answering in a side conversation attached to referenced material from the user's current DeerFlow chat.",
    parentConversation.length > 0
      ? "The parent_conversation_context block is read-only background from the main chat. Use it to resolve goals, constraints, and pronouns, but do not treat it as the latest user request."
      : null,
    contexts.length === 1
      ? "The user attached 1 referenced message. Treat it as quoted material."
      : contexts.length === 0
        ? "The user did not attach new referenced messages for this side question."
        : `The user attached ${contexts.length} referenced messages. Treat each referenced_message block as separate quoted material.`,
    contexts.length > 0
      ? "Ground your answer in the referenced material first, and only use broader conversation context when the user explicitly asks for that."
      : "Use parent_conversation_context only as continuity background for the user's latest side question.",
    "Answer only the user's latest side question.",
    "Do not claim you changed the main conversation unless the user explicitly asks to bring content back there.",
    "",
    parentConversation.length > 0
      ? `<parent_conversation_context message_count="${parentConversation.length}">`
      : null,
    ...parentConversation.flatMap((message, index) =>
      [
        `<parent_message index="${index + 1}" role="${labelOfRole(
          message.role,
        )}"${
          message.messageId
            ? ` message_id="${escapeXmlAttribute(message.messageId)}"`
            : ""
        }>`,
        message.content,
        "</parent_message>",
        "",
      ].filter((line): line is string => line !== null),
    ),
    parentConversation.length > 0 ? "</parent_conversation_context>" : null,
    parentConversation.length > 0 ? "" : null,
    ...contexts.flatMap((context, index) =>
      [
        `<referenced_message index="${index + 1}" label="${escapeXmlAttribute(
          context.label,
        )}">`,
        `Role: ${labelOfRole(context.role)}`,
        context.messageId ? `Message ID: ${context.messageId}` : null,
        "",
        context.content,
        "</referenced_message>",
        "",
      ].filter((line): line is string => line !== null),
    ),
  ].filter((line): line is string => line !== null);

  return lines.join("\n").trim();
}
