import type { AgentThreadState, GoalState } from "./types";

type ThreadStatePatch = Partial<AgentThreadState>;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isGoalState(value: unknown): value is GoalState {
  return (
    isRecord(value) &&
    typeof value.objective === "string" &&
    value.status === "active" &&
    typeof value.created_at === "string" &&
    typeof value.updated_at === "string"
  );
}

const RENDERED_THREAD_STATE_KEYS = ["title", "artifacts", "todos", "goal"];

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
