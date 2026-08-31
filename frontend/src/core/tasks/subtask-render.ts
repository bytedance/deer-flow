import { extractTextFromMessage, type MessageGroup } from "../messages/utils";

import {
  derivePendingSubtaskStatus,
  parseSubtaskResult,
} from "./subtask-result";
import { isTerminalSubtaskStatus } from "./subtask-update";
import type { Subtask } from "./types";

export interface RenderedSubtasks {
  tasks: Map<string, Subtask>;
  updates: Array<Partial<Subtask> & { id: string }>;
}

export function resolveRenderedSubtask(
  liveTask: Subtask | undefined,
  fallbackTask: Subtask | undefined,
): Subtask | undefined {
  if (!fallbackTask) {
    return liveTask;
  }

  if (!liveTask) {
    return fallbackTask;
  }

  if (!isTerminalSubtaskStatus(fallbackTask.status)) {
    return liveTask.status ? liveTask : { ...fallbackTask, ...liveTask };
  }

  return {
    ...liveTask,
    ...fallbackTask,
    steps: liveTask.steps ?? fallbackTask.steps,
    latestMessage: liveTask.latestMessage ?? fallbackTask.latestMessage,
  };
}

export function collectRenderedSubtasks(
  groups: MessageGroup[],
  isGroupLoading: (groupIndex: number) => boolean,
  failedLabel: string,
): RenderedSubtasks {
  const tasks = new Map<string, Subtask>();
  const updates: Array<Partial<Subtask> & { id: string }> = [];

  for (const [groupIndex, group] of groups.entries()) {
    if (group.type !== "assistant:subagent") {
      continue;
    }

    const groupIsLoading = isGroupLoading(groupIndex);

    for (const message of group.messages) {
      if (message.type === "ai") {
        for (const toolCall of message.tool_calls ?? []) {
          if (toolCall.name !== "task" || !toolCall.id) {
            continue;
          }
          const status = derivePendingSubtaskStatus(
            toolCall.id,
            group.messages,
            groupIsLoading,
          );
          const task: Subtask = {
            id: toolCall.id,
            subagent_type: toolCall.args.subagent_type,
            description: toolCall.args.description,
            prompt: toolCall.args.prompt,
            status,
            ...(status === "failed" ? { error: failedLabel } : {}),
          };
          tasks.set(task.id, { ...(tasks.get(task.id) ?? {}), ...task });
          updates.push(task);
        }
        continue;
      }

      if (message.type === "tool" && message.tool_call_id) {
        const update = {
          id: message.tool_call_id,
          ...parseSubtaskResult(
            extractTextFromMessage(message),
            message.additional_kwargs,
          ),
        };
        const existingTask = tasks.get(message.tool_call_id);
        if (existingTask) {
          tasks.set(message.tool_call_id, { ...existingTask, ...update });
        }
        updates.push(update);
      }
    }
  }

  return { tasks, updates };
}
