import type { Message } from "@langchain/langgraph-sdk";

import { extractTextFromMessage } from "@/core/messages/utils";

import { parseSubtaskResult } from "./subtask-result";
import type { Subtask } from "./types";

export function buildSubtaskMapFromMessages(
  messages: Message[],
): Record<string, Subtask> {
  const tasks: Record<string, Subtask> = {};

  for (const message of messages) {
    if (message.type === "ai") {
      for (const toolCall of message.tool_calls ?? []) {
        if (toolCall.name !== "task" || !toolCall.id) {
          continue;
        }

        tasks[toolCall.id] = {
          id: toolCall.id,
          status: "in_progress",
          subagent_type: String(toolCall.args?.subagent_type ?? ""),
          description: String(toolCall.args?.description ?? ""),
          prompt: String(toolCall.args?.prompt ?? ""),
        };
      }
      continue;
    }

    if (message.type !== "tool" || !message.tool_call_id) {
      continue;
    }

    const task = tasks[message.tool_call_id];
    if (!task) {
      continue;
    }

    tasks[message.tool_call_id] = {
      ...task,
      ...parseSubtaskResult(extractTextFromMessage(message)),
    };
  }

  return tasks;
}
