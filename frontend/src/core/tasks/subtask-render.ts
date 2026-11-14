import type { Message } from "@langchain/langgraph-sdk";

import { extractTextFromMessage, type MessageGroup } from "../messages/utils";

import { subtaskKey } from "./identity";
import { resolveSubtaskDescription } from "./presentation";
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

/** Only this group's matching result after the task invocation supplies evidence. */
export function findSubtaskResultMessage(
  group: MessageGroup,
  taskId: string,
  dispatchId?: string,
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
      invoked = !dispatchId || message.id === dispatchId;
    if (
      invoked &&
      message.type === "tool" &&
      message.name === "task" &&
      message.tool_call_id === taskId
    )
      if (
        !dispatchId ||
        !message.additional_kwargs?.subagent_dispatch_id ||
        message.additional_kwargs.subagent_dispatch_id === dispatchId
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
  const tasks = new Map<string, Subtask>();
  const updates: Array<Partial<Subtask> & { id: string }> = [];
  const dispatches = new Map<string, string>();

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
          const matchingResult = findSubtaskResultMessage(
            group,
            toolCall.id,
            message.id,
          );
          const status = derivePendingSubtaskStatus(
            toolCall.id,
            matchingResult ? [matchingResult] : [],
            groupIsLoading,
          );
          const task: Subtask = {
            id: subtaskKey(toolCall.id, message.id),
            providerCallId: toolCall.id,
            dispatchId: message.id,
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
          if (message.id) dispatches.set(toolCall.id, message.id);
          tasks.set(task.id, { ...(tasks.get(task.id) ?? {}), ...task });
          updates.push(task);
        }
        continue;
      }

      if (message.type === "tool" && message.tool_call_id) {
        if (message.additional_kwargs?.subagent_pending === true) continue;
        const update = {
          id: subtaskKey(
            message.tool_call_id,
            typeof message.additional_kwargs?.subagent_dispatch_id === "string"
              ? message.additional_kwargs.subagent_dispatch_id
              : dispatches.get(message.tool_call_id),
          ),
          ...parseSubtaskResult(
            extractTextFromMessage(message),
            message.additional_kwargs,
          ),
        };
        const existingTask = tasks.get(update.id);
        if (existingTask) {
          tasks.set(update.id, { ...existingTask, ...update });
        }
        updates.push(update);
      }
    }
  }

  return { tasks, updates };
}
