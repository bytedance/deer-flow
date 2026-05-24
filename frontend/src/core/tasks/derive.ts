import type { Message } from "@langchain/langgraph-sdk";

import { extractTextFromMessage } from "../messages/utils";

import { parseSubtaskResult } from "./subtask-result";
import type { Subtask } from "./types";

/**
 * Derive the subtask card map from the current thread message list.
 *
 * Bytedance/deer-flow issue #3147: the old data flow built this map by
 * calling `updateSubtask` *during render* from `MessageList`, which silently
 * mutated the SubtaskContext object without triggering a re-render (only
 * the SSE `latestMessage` path called `setState`). That worked by accident
 * but is exactly the render-time mutation React Strict Mode warns about
 * and the kind of pattern that masks card-stuck regressions like
 * `#3107` BUG-007.
 *
 * Replace it with a pure function over the message list. `MessageList`
 * computes the map inside a `useMemo` and hands each entry to
 * `SubtaskCard` as a prop, so render stays read-only. The SSE-driven
 * `latestMessage` path stays separate (see `useUpdateLatestMessage`).
 */
export function buildSubtaskMapFromMessages(
  messages: readonly Message[],
): Record<string, Subtask> {
  const tasks: Record<string, Subtask> = {};

  for (const message of messages) {
    if (message.type === "ai") {
      for (const toolCall of message.tool_calls ?? []) {
        if (toolCall.name !== "task" || !toolCall.id) continue;
        // Seed the card in `in_progress` the moment the AI emits the
        // tool_call. The matching ToolMessage flips it to terminal below.
        tasks[toolCall.id] = {
          id: toolCall.id,
          subagent_type: String(toolCall.args?.subagent_type ?? ""),
          description: String(toolCall.args?.description ?? ""),
          prompt: String(toolCall.args?.prompt ?? ""),
          status: "in_progress",
        };
      }
    } else if (message.type === "tool") {
      const taskId = message.tool_call_id;
      if (!taskId || !(taskId in tasks)) continue;
      // NOTE: `parseSubtaskResult` will gain a second argument for
      // ``additional_kwargs.subagent_status`` once #3146 lands. This call
      // site is forward-compatible: when the signature widens, we just
      // pass `message.additional_kwargs` here and the structured field
      // will take precedence over text parsing automatically.
      const parsed = parseSubtaskResult(extractTextFromMessage(message));
      tasks[taskId] = { ...tasks[taskId], ...parsed } as Subtask;
    }
  }

  return tasks;
}
