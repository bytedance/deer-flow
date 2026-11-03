import type { Message } from "@langchain/langgraph-sdk";

import { extractTextFromMessage, type MessageGroup } from "../messages/utils";

import { resolveSubtaskDescription } from "./presentation";
import {
  derivePendingSubtaskStatus,
  parseSubtaskResult,
} from "./subtask-result";
import { isTerminalSubtaskStatus } from "./subtask-update";
import type { Subtask } from "./types";

export interface RenderedSubtasks {
  /**
   * Message-derived task snapshots per message group (turn). Keeping them
   * per-group is what stops a provider that reuses one `tool_call_id` across
   * runs from letting a later turn's card overwrite an earlier turn's.
   */
  tasksByGroup: Map<number, Map<string, Subtask>>;
  updates: Array<Partial<Subtask> & { id: string }>;
  /**
   * Group index of the last turn that used each `tool_call_id`. The live
   * subtask context is keyed by bare `tool_call_id`, so when a provider reuses
   * one across runs only that last turn's card may take live state as its own;
   * earlier turns render their own snapshot instead.
   */
  ownerGroupByTaskId: Map<string, number>;
}

/** Only this group's matching result after the task invocation supplies evidence. */
export function findSubtaskResultMessage(
  group: MessageGroup,
  taskId: string,
): Message | undefined {
  if (group.type !== "assistant:subagent") return undefined;
  let invoked = false;
  for (const message of group.messages) {
    if (
      message.type === "ai" &&
      message.tool_calls?.some(
        (call) => call.name === "task" && call.id === taskId,
      )
    )
      invoked = true;
    if (
      invoked &&
      message.type === "tool" &&
      message.name === "task" &&
      message.tool_call_id === taskId
    )
      return message;
  }
  return undefined;
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
    return {
      ...fallbackTask,
      ...liveTask,
      subagent_type: fallbackTask.subagent_type ?? liveTask.subagent_type,
      description: fallbackTask.description ?? liveTask.description,
      prompt: fallbackTask.prompt ?? liveTask.prompt,
      status: liveTask.status ?? fallbackTask.status,
    };
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
  subtaskLabel: string,
): RenderedSubtasks {
  const tasksByGroup = new Map<number, Map<string, Subtask>>();
  const ownerGroupByTaskId = new Map<string, number>();
  const updates: Array<Partial<Subtask> & { id: string }> = [];

  const rememberTaskId = (taskId: string, groupIndex: number) => {
    ownerGroupByTaskId.set(taskId, groupIndex);
  };

  for (const [groupIndex, group] of groups.entries()) {
    if (group.type !== "assistant:subagent") {
      continue;
    }

    const groupIsLoading = isGroupLoading(groupIndex);
    const tasks = new Map<string, Subtask>();
    tasksByGroup.set(groupIndex, tasks);

    for (const message of group.messages) {
      if (message.type === "ai") {
        for (const toolCall of message.tool_calls ?? []) {
          if (toolCall.name !== "task" || !toolCall.id) {
            continue;
          }
          rememberTaskId(toolCall.id, groupIndex);
          const status = derivePendingSubtaskStatus(
            toolCall.id,
            group.messages,
            groupIsLoading,
          );
          const task: Subtask = {
            id: toolCall.id,
            subagent_type: toolCall.args.subagent_type,
            description: resolveSubtaskDescription(
              toolCall.args.description,
              toolCall.args.prompt,
              subtaskLabel,
            ),
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
        rememberTaskId(message.tool_call_id, groupIndex);
        if (message.additional_kwargs?.subagent_pending === true) continue;
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

  return { tasksByGroup, updates, ownerGroupByTaskId };
}
