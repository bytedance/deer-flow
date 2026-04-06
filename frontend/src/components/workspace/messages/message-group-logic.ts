import type { Message } from "@langchain/langgraph-sdk";

import {
  extractReasoningContentFromMessage,
  findToolCallResult,
} from "../../../core/messages/utils";

interface GenericCoTStep<T extends string = string> {
  id?: string;
  messageId?: string;
  type: T;
}

export interface CoTReasoningStep extends GenericCoTStep<"reasoning"> {
  reasoning: string | null;
}

export interface CoTToolCallStep extends GenericCoTStep<"toolCall"> {
  name: string;
  args: Record<string, unknown>;
  isComplete: boolean;
  result?: string | Record<string, unknown>;
}

export type CoTStep = CoTReasoningStep | CoTToolCallStep;

export function isToolCallStep(step: CoTStep): step is CoTToolCallStep {
  return step.type === "toolCall";
}

export function isReasoningStep(step: CoTStep): step is CoTReasoningStep {
  return step.type === "reasoning";
}

export function convertToSteps(messages: Message[]): CoTStep[] {
  const steps: CoTStep[] = [];
  for (const message of messages) {
    if (message.type !== "ai") {
      continue;
    }

    const reasoning = extractReasoningContentFromMessage(message);
    if (reasoning) {
      steps.push({
        id: message.id,
        messageId: message.id,
        type: "reasoning",
        reasoning,
      });
    }

    for (const toolCall of message.tool_calls ?? []) {
      if (toolCall.name === "task") {
        continue;
      }

      const step: CoTToolCallStep = {
        id: toolCall.id,
        messageId: message.id,
        type: "toolCall",
        name: toolCall.name,
        args: toolCall.args,
        isComplete: false,
      };

      const toolCallId = toolCall.id;
      if (toolCallId) {
        const toolCallResult = findToolCallResult(toolCallId, messages);
        if (toolCallResult !== undefined) {
          step.isComplete = true;
        }
        if (toolCallResult) {
          try {
            step.result = JSON.parse(toolCallResult);
          } catch {
            step.result = toolCallResult;
          }
        }
      }

      steps.push(step);
    }
  }
  return steps;
}

export function getVisibleToolCallSteps(steps: CoTStep[]): CoTToolCallStep[] {
  const toolCallSteps = steps.filter(isToolCallStep);
  const lastToolCallStep = toolCallSteps.at(-1);

  if (!lastToolCallStep) {
    return [];
  }

  if (!lastToolCallStep.messageId) {
    return [lastToolCallStep];
  }

  const lastBatch = toolCallSteps.filter(
    (step) => step.messageId === lastToolCallStep.messageId,
  );

  return lastBatch.length > 0 ? lastBatch : [lastToolCallStep];
}

export function getAboveVisibleSteps(
  steps: CoTStep[],
  visibleToolCallSteps: CoTToolCallStep[],
): CoTStep[] {
  const firstVisibleToolCall = visibleToolCallSteps[0];

  if (!firstVisibleToolCall) {
    return [];
  }

  const firstVisibleIndex = steps.indexOf(firstVisibleToolCall);
  if (firstVisibleIndex < 0) {
    return [];
  }

  return steps.slice(0, firstVisibleIndex);
}

export function getLastReasoningStep(
  steps: CoTStep[],
  visibleToolCallSteps: CoTToolCallStep[],
): CoTReasoningStep | undefined {
  if (visibleToolCallSteps.length > 0) {
    const lastVisibleToolCall =
      visibleToolCallSteps[visibleToolCallSteps.length - 1];
    if (lastVisibleToolCall) {
      const lastVisibleIndex = steps.lastIndexOf(lastVisibleToolCall);
      if (lastVisibleIndex >= 0) {
        return steps.slice(lastVisibleIndex + 1).find(isReasoningStep);
      }
    }
  }

  return steps.filter(isReasoningStep).at(-1);
}
