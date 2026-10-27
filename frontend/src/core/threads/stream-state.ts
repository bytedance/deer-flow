import type { AgentThreadState, ArtifactEntry, GoalState } from "./types";

type ThreadStatePatch = Partial<AgentThreadState>;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * An active goal as the backend judges one (`status` "active"), so a
 * malformed or inactive `goal` in history, worker frames or a status read
 * never renders, and the bar and the edit lock agree with the server. POST
 * /state and run input can store one without `created_at`/`updated_at`.
 * `goal_outcome` is not folded here: only the worker's clear writes it,
 * never through `updates`.
 */
export function isGoalState(value: unknown): value is GoalState {
  return (
    isRecord(value) &&
    typeof value.objective === "string" &&
    value.status === "active"
  );
}

const RENDERED_THREAD_STATE_KEYS = [
  "title",
  "artifacts",
  "tool_artifacts",
  "todos",
  "goal",
];

export function hasRenderedThreadStateUpdate(data: unknown): boolean {
  if (!isRecord(data)) return false;
  return Object.values(data).some(
    (update) =>
      isRecord(update) &&
      RENDERED_THREAD_STATE_KEYS.some((key) => Object.hasOwn(update, key)),
  );
}

function mergeArtifacts(
  existing: AgentThreadState["artifacts"],
  incoming: unknown,
): string[] | undefined {
  if (incoming == null || !Array.isArray(incoming)) {
    return undefined;
  }
  if (!incoming.every((path) => typeof path === "string")) {
    return undefined;
  }

  return [...new Set([...(existing ?? []), ...incoming])];
}

function isArtifactEntry(value: unknown): value is ArtifactEntry {
  return (
    isRecord(value) &&
    [
      "handle",
      "tool_name",
      "tool_call_id",
      "artifact_type",
      "display_name",
      "real_ref",
    ].every((key) => typeof value[key] === "string") &&
    Number.isInteger(value.call_index)
  );
}

function mergeToolArtifacts(
  existing: ArtifactEntry[] | undefined,
  incoming: unknown,
): ArtifactEntry[] | undefined {
  if (!Array.isArray(incoming)) return undefined;
  // Same-handle updates replace metadata without moving first-seen order.
  // Capture can append a retention directive after its entries.
  const byHandle = new Map<string, ArtifactEntry>();
  for (const item of [...(existing ?? []), ...incoming]) {
    if (isArtifactEntry(item)) byHandle.set(item.handle, item);
  }
  let keep = 1000;
  for (let index = incoming.length - 1; index >= 0; index--) {
    const item: unknown = incoming[index];
    if (isRecord(item) && item.op === "trim_to") {
      if (
        typeof item.keep === "number" &&
        Number.isInteger(item.keep) &&
        item.keep > 0
      ) {
        keep = Math.min(item.keep, keep);
      }
      break;
    }
  }
  return [...byHandle.values()].slice(-keep);
}

/**
 * Fold a LangGraph `updates` frame into the state fields rendered by the chat
 * UI. Updates are grouped by node name and carry reducer inputs, not complete
 * state snapshots, so these fields must mirror the reducers in
 * `deerflow.agents.thread_state` rather than being shallowly assigned.
 *
 * `messages` is deliberately excluded. The SDK's `messages-tuple` manager owns
 * chunk assembly and same-id replacement; applying the node's messages update
 * through `mutate` as well would duplicate messages and bypass chunk merging.
 */
export function reduceThreadStateUpdates(
  previous: AgentThreadState,
  data: unknown,
): ThreadStatePatch | undefined {
  if (!isRecord(data)) {
    return undefined;
  }

  const patch: ThreadStatePatch = {};
  let artifacts = previous.artifacts;
  let toolArtifacts = previous.tool_artifacts;
  let hasPatch = false;

  for (const update of Object.values(data)) {
    if (!isRecord(update)) {
      continue;
    }

    if (Object.hasOwn(update, "title") && typeof update.title === "string") {
      patch.title = update.title;
      hasPatch = true;
    }

    if (Object.hasOwn(update, "artifacts")) {
      const mergedArtifacts = mergeArtifacts(artifacts, update.artifacts);
      if (mergedArtifacts !== undefined) {
        artifacts = mergedArtifacts;
        patch.artifacts = mergedArtifacts;
        hasPatch = true;
      }
    }

    if (Object.hasOwn(update, "tool_artifacts")) {
      const merged = mergeToolArtifacts(toolArtifacts, update.tool_artifacts);
      if (merged !== undefined) {
        toolArtifacts = merged;
        patch.tool_artifacts = merged;
        hasPatch = true;
      }
    }

    // DeerFlow's merge_todos treats null as "this node did not touch todos"
    // and an empty list as an explicit clear.
    if (
      Object.hasOwn(update, "todos") &&
      update.todos !== null &&
      Array.isArray(update.todos)
    ) {
      patch.todos = update.todos;
      hasPatch = true;
    }

    // merge_goal likewise preserves the prior goal for null writes.
    if (
      Object.hasOwn(update, "goal") &&
      update.goal !== null &&
      isGoalState(update.goal)
    ) {
      patch.goal = update.goal;
      hasPatch = true;
    }
  }

  return hasPatch ? patch : undefined;
}
