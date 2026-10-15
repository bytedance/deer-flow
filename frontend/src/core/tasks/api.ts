import { fetch } from "../api/fetcher";
import { getBackendBaseURL } from "../config";

import { eventsToSteps, type SubtaskStep } from "./steps";

/** Default per-request page size; matches the events endpoint's default. */
const SUBTASK_STEPS_PAGE_SIZE = 500;
/** Safety bound on pagination so a misbehaving cursor can't loop forever. */
const SUBTASK_STEPS_MAX_PAGES = 100;

type FetchedEvent = Parameters<typeof eventsToSteps>[0][number] & {
  seq?: number;
};

/**
 * Fetch a subtask's persisted step history for a historical run (#3779).
 *
 * Scoped server-side to this `taskId` (and to `subagent.step` events) and paged
 * forward with an `after_seq` cursor until a short page, so the run-wide event
 * limit can never truncate a subagent's step timeline — even for long runs or
 * runs with several subagents. Used by the subtask card to backfill steps on
 * expand when the live SSE steps are gone (e.g. after a page reload).
 */
export async function fetchSubtaskSteps(
  threadId: string,
  runId: string,
  taskId: string,
  pageSize: number = SUBTASK_STEPS_PAGE_SIZE,
): Promise<SubtaskStep[]> {
  const base = `${getBackendBaseURL()}/api/threads/${encodeURIComponent(
    threadId,
  )}/runs/${encodeURIComponent(runId)}/events`;

  const events: FetchedEvent[] = [];
  let afterSeq: number | undefined;

  for (let page = 0; page < SUBTASK_STEPS_MAX_PAGES; page++) {
    const params = new URLSearchParams({
      event_types: "subagent.step",
      task_id: taskId,
      limit: String(pageSize),
    });
    if (afterSeq !== undefined) {
      params.set("after_seq", String(afterSeq));
    }

    const res = await fetch(`${base}?${params.toString()}`);
    if (!res.ok) {
      throw new Error(`Failed to fetch subtask steps: ${res.status}`);
    }
    const batch = (await res.json()) as FetchedEvent[];
    events.push(...batch);

    if (batch.length < pageSize) {
      break;
    }
    const lastSeq = batch[batch.length - 1]?.seq;
    if (lastSeq === undefined) {
      break; // can't advance the cursor; stop rather than refetch page 0 forever
    }
    afterSeq = lastSeq;
  }

  return eventsToSteps(events, taskId);
}
