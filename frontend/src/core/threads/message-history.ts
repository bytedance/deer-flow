import type { Message } from "@langchain/langgraph-sdk";

export function appendUniqueMessages(
  previousMessages: Message[],
  incomingMessages: Message[],
  position: "append" | "prepend" = "append",
): Message[] {
  const existingIds = new Set(previousMessages.map((message) => message.id));
  const newMessages = incomingMessages.filter(
    (message) => !existingIds.has(message.id),
  );

  if (newMessages.length === 0) {
    return previousMessages;
  }

  return position === "prepend"
    ? [...newMessages, ...previousMessages]
    : [...previousMessages, ...newMessages];
}
