import type { AIMessage } from "@langchain/langgraph-sdk";

export interface Subtask {
  id: string;
  status: "in_progress" | "completed" | "failed";
  subagent_type: string;
  description: string;
  latestMessage?: AIMessage;
  /**
   * All intermediate AI messages received while the subtask was running.
   * Optional because Subtask objects can originate from paths that have not
   * been migrated to initialise it (e.g. legacy persisted state, third-party
   * callers of `updateSubtask`). Callers must handle `undefined`.
   */
  messageHistory?: AIMessage[];
  /**
   * `message_index` values already accumulated into `messageHistory`, in the
   * order they were received. Used to dedupe `task_running` events on stream
   * resume (see `useStream({ reconnectOnMount, streamResumable })` and the
   * backend `task_tool` writer that emits `message_index`). Persisted on
   * the task so dedup survives React re-renders.
   */
  seenMessageIndices?: number[];
  prompt: string;
  result?: string;
  error?: string;
}
