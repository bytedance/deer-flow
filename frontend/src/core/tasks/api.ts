import { fetch } from "../api/fetcher";
import { getBackendBaseURL } from "../config";

import { eventsToSteps, type SubtaskStep } from "./steps";

/**
 * Fetch a subtask's persisted step history for a historical run (#3779).
 *
 * Reuses the run-events endpoint, filtered to the subagent lifecycle event
 * types, and projects the `subagent.step` events for `taskId` into ordered
 * steps. Used by the subtask card to backfill steps on expand when the live
 * SSE steps are gone (e.g. after a page reload).
 */
export async function fetchSubtaskSteps(
  threadId: string,
  runId: string,
  taskId: string,
): Promise<SubtaskStep[]> {
  const url = `${getBackendBaseURL()}/api/threads/${encodeURIComponent(
    threadId,
  )}/runs/${encodeURIComponent(
    runId,
  )}/events?event_types=subagent.start,subagent.step,subagent.end`;

  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`Failed to fetch subtask steps: ${res.status}`);
  }
  const events = (await res.json()) as Parameters<typeof eventsToSteps>[0];
  return eventsToSteps(events, taskId);
}
