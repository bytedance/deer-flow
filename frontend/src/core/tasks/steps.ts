import type { AIMessage } from "@langchain/langgraph-sdk";

import type { SubtaskStep } from "./types";

function normalizeMessageIndex(messageIndex: unknown) {
  return typeof messageIndex === "number" &&
    Number.isInteger(messageIndex) &&
    messageIndex > 0
    ? messageIndex
    : undefined;
}

export function mergeSubtaskStep(
  steps: SubtaskStep[] | undefined,
  message: AIMessage,
  messageIndex?: number,
): SubtaskStep[] {
  const next = [...(steps ?? [])];
  const normalizedMessageIndex = normalizeMessageIndex(messageIndex);
  const indexMatch =
    normalizedMessageIndex !== undefined
      ? next.findIndex((step) => step.messageIndex === normalizedMessageIndex)
      : -1;
  const idMatch = message.id
    ? next.findIndex((step) => step.message.id === message.id)
    : -1;
  const existingIndex = indexMatch >= 0 ? indexMatch : idMatch;
  const nextStep: SubtaskStep = {
    message,
    ...(normalizedMessageIndex !== undefined
      ? { messageIndex: normalizedMessageIndex }
      : {}),
  };

  if (existingIndex >= 0) {
    next[existingIndex] = nextStep;
  } else {
    next.push(nextStep);
  }

  return next.sort((a, b) => {
    if (a.messageIndex !== undefined && b.messageIndex !== undefined) {
      return a.messageIndex - b.messageIndex;
    }
    if (a.messageIndex !== undefined) {
      return -1;
    }
    if (b.messageIndex !== undefined) {
      return 1;
    }
    return 0;
  });
}
