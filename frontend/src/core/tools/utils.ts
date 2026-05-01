import type { ToolCall } from "@langchain/core/messages";
import type { AIMessage, Message } from "@langchain/langgraph-sdk";

import type { Translations } from "../i18n";
import {
  extractReasoningContentFromMessage,
  findToolCallResult,
  hasToolCalls,
} from "../messages/utils";

export function explainLastToolCall(message: AIMessage, t: Translations) {
  if (hasToolCalls(message)) {
    const lastToolCall = message.tool_calls![message.tool_calls!.length - 1]!;
    return explainToolCall(lastToolCall, t);
  }
  return t.common.thinking;
}

export function explainToolCall(toolCall: ToolCall, t: Translations) {
  if (toolCall.name === "web_search" || toolCall.name === "image_search") {
    return t.toolCalls.searchFor(toolCall.args.query);
  } else if (toolCall.name === "web_fetch") {
    return t.toolCalls.viewWebPage;
  } else if (toolCall.name === "present_files") {
    return t.toolCalls.presentFiles;
  } else if (toolCall.name === "write_todos") {
    return t.toolCalls.writeTodos;
  } else if (toolCall.args.description) {
    return toolCall.args.description;
  } else {
    return t.toolCalls.useTool(toolCall.name);
  }
}

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
  result?: string | Record<string, unknown>;
}

export type CoTStep = CoTReasoningStep | CoTToolCallStep;

export function convertToToolCallSteps(messages: Message[]): CoTStep[] {
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
    for (const tool_call of message.tool_calls ?? []) {
      if (tool_call.name === "task") {
        continue;
      }
      const step: CoTToolCallStep = {
        id: tool_call.id,
        messageId: message.id,
        type: "toolCall",
        name: tool_call.name,
        args: tool_call.args,
      };
      const toolCallId = tool_call.id;
      if (toolCallId) {
        const toolCallResult = findToolCallResult(toolCallId, messages);
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

export function partitionStepsForDisplay(steps: CoTStep[]): {
  aboveSteps: CoTStep[];
  activeSteps: CoTToolCallStep[];
} {
  const toolCallSteps = steps.filter(
    (step): step is CoTToolCallStep => step.type === "toolCall",
  );
  if (toolCallSteps.length === 0) {
    return { aboveSteps: [], activeSteps: [] };
  }

  const lastAIMessageId = toolCallSteps[toolCallSteps.length - 1]!.messageId;
  const activeSteps = toolCallSteps.filter(
    (step) =>
      step.messageId !== undefined && step.messageId === lastAIMessageId,
  );
  if (activeSteps.length === 0) {
    return { aboveSteps: [], activeSteps: [] };
  }

  const firstActiveIndex = steps.indexOf(activeSteps[0]!);
  const aboveSteps = steps.slice(0, firstActiveIndex);

  return { aboveSteps, activeSteps };
}
