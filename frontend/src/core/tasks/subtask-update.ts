import { mergeSteps } from "./steps";
import type { Subtask } from "./types";

export function isTerminalSubtaskStatus(status: Subtask["status"] | undefined) {
  return status === "completed" || status === "failed";
}

/**
 * Pure state transition for a single subtask update (#3779).
 *
 * Kept separate from the React hook so it can be unit-tested and, crucially, so
 * the hook can compute `next` from the *latest* `previous` handed to a
 * functional `setTasks` updater — not a stale `tasks` snapshot captured in a
 * closure. Deriving `next` from whatever `previous` the caller passes is what
 * lets an in-flight `fetchSubtaskSteps().then(...)` merge into current state
 * instead of clobbering SSE steps / sibling subtasks that arrived meanwhile.
 *
 * `steps` are treated as deltas: they are merged into `previous.steps`
 * (deduped/ordered by message_index) rather than replacing them, so live SSE
 * steps and fetched-on-expand backfill build one timeline.
 */
export function computeNextSubtask(
  previous: Subtask | undefined,
  task: Partial<Subtask> & { id: string },
): { next: Subtask; becameTerminal: boolean; changed: boolean } {
  const previousStatus = previous?.status;

  // MessageList writes the pending task tool-call state before parsing the
  // matching ToolMessage in the same render. Keep terminal results stable
  // across the next render so the refresh notification does not loop.
  const next = {
    ...previous,
    ...task,
    ...(task.status === "in_progress" && isTerminalSubtaskStatus(previousStatus)
      ? { status: previousStatus }
      : {}),
  } as Subtask;

  if (task.steps) {
    next.steps = mergeSteps(previous?.steps ?? [], task.steps);
  }

  // Usage events are cumulative snapshots. A delayed older frame must never
  // make the folded card appear to spend fewer tokens than it already did.
  if (
    task.usage &&
    previous?.usage &&
    task.usage.totalTokens < previous.usage.totalTokens
  ) {
    next.usage = previous.usage;
  }

  const becameTerminal =
    isTerminalSubtaskStatus(next.status) && previousStatus !== next.status;

  return { next, becameTerminal, changed: subtaskChanged(previous, next) };
}

/**
 * Did `next` materially differ from `previous`?
 *
 * The terminal ToolMessage is re-parsed on *every* MessageList render, and
 * `parseSubtaskResult` rebuilds `modelName`/`usage` into a fresh object each
 * time. Comparing by value (not reference) is what lets the hook skip a
 * redundant `setTasks` for an idempotent re-parse — without it the new object
 * identity drives an infinite render loop once a subagent finishes.
 */
function subtaskChanged(prev: Subtask | undefined, next: Subtask): boolean {
  if (!prev) {
    return true;
  }
  return (
    prev.status !== next.status ||
    prev.modelName !== next.modelName ||
    prev.result !== next.result ||
    prev.error !== next.error ||
    prev.stopReason !== next.stopReason ||
    prev.subagent_type !== next.subagent_type ||
    prev.description !== next.description ||
    prev.prompt !== next.prompt ||
    prev.latestMessage !== next.latestMessage ||
    prev.steps !== next.steps ||
    !usageEquals(prev.usage, next.usage)
  );
}

function usageEquals(a: Subtask["usage"], b: Subtask["usage"]): boolean {
  if (a === b) {
    return true;
  }
  if (!a || !b) {
    return false;
  }
  return (
    a.inputTokens === b.inputTokens &&
    a.outputTokens === b.outputTokens &&
    a.totalTokens === b.totalTokens
  );
}

export type SubtaskNotification = "eager" | "deferred" | "none";

/**
 * Decide how `useUpdateSubtask` should publish a computed transition.
 *
 * - `deferred`: a terminal transition. These arrive while MessageList renders
 *   (it parses the ToolMessage inline), so we must not `setTasks` mid-render;
 *   the hook flips a ref and publishes in an after-render effect instead.
 * - `eager`: a live SSE update (steps / latestMessage / model / usage) that
 *   actually changed state — publish immediately from the async callback.
 * - `none`: nothing changed. Critically, a re-parsed terminal result still
 *   carries `modelName`/`usage`, so gating on `changed` (not mere presence) is
 *   what stops the render loop.
 */
export function subtaskNotification(
  task: Partial<Subtask> & { id: string },
  transition: { becameTerminal: boolean; changed: boolean },
): SubtaskNotification {
  if (transition.becameTerminal) {
    return "deferred";
  }
  if (
    transition.changed &&
    (task.latestMessage || task.steps || task.modelName || task.usage)
  ) {
    return "eager";
  }
  return "none";
}
