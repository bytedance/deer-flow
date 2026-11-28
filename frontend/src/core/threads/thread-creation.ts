import { markRunError } from "./run-error";

/**
 * Which send asked for the thread the SDK created.
 *
 * `onThreadId` reports the id of a conversation the SDK created, but not the
 * send that asked for it. A submission carries a page id (a new chat's
 * placeholder, or the sidecar's gateway-created id) and the SDK passes it to
 * `threads.create`, so recording that pair at the call lets the hook bind the
 * report to the send that produced it instead of guessing from submission
 * order — a released attempt whose create was cancelled would otherwise take
 * the next attempt's thread (#8092 review).
 */
const requestedByCreated = new Map<string, string>();

/** Clients already wrapped, so a re-render cannot stack wrappers. */
const taggedClients = new WeakSet<object>();

/** Bound: a report that never arrives must not keep the map growing. */
const MAX_PENDING_CREATIONS = 16;

export function markThreadCreation(
  createdThreadId: string,
  requestedThreadId: string,
): void {
  if (!createdThreadId || !requestedThreadId) {
    return;
  }
  requestedByCreated.delete(createdThreadId);
  requestedByCreated.set(createdThreadId, requestedThreadId);
  while (requestedByCreated.size > MAX_PENDING_CREATIONS) {
    const oldest = requestedByCreated.keys().next().value;
    if (oldest === undefined) break;
    requestedByCreated.delete(oldest);
  }
}

/** Read and forget the submission id that asked for `createdThreadId`. */
export function takeRequestedThreadId(
  createdThreadId: string,
): string | undefined {
  const requested = requestedByCreated.get(createdThreadId);
  if (requested !== undefined) {
    requestedByCreated.delete(createdThreadId);
  }
  return requested;
}

type ThreadCreator = {
  create?: (payload?: { threadId?: string }, ...rest: unknown[]) => unknown;
};

type CreateClient = { threads: ThreadCreator };

/**
 * Record `created → requested` for every conversation the SDK creates.
 *
 * The record is what lets `onThreadId` bind a report to the send that asked for
 * the thread; without it the hook has only submission order, and a released
 * attempt whose creation was cancelled leaves a stale head that steals the
 * next attempt's id.
 */
export function withThreadCreationTagging<T extends CreateClient>(
  client: T,
): T {
  const threads = client.threads as ThreadCreator | undefined;
  // Test doubles and non-SDK clients may not expose a thread reader; leave them
  // untouched so `onThreadId` falls back to submission order.
  if (
    !threads ||
    typeof threads.create !== "function" ||
    taggedClients.has(client)
  ) {
    return client;
  }
  const create = threads.create.bind(threads);
  threads.create = async (payload, ...rest) => {
    const requested = payload?.threadId;
    try {
      const created = (await create(payload, ...rest)) as {
        thread_id?: unknown;
      } | null;
      if (
        typeof requested === "string" &&
        typeof created?.thread_id === "string"
      ) {
        markThreadCreation(created.thread_id, requested);
      }
      return created;
    } catch (error) {
      // A refused create reaches `onError` without run metadata, so the hook
      // can only settle it by the submission that asked for the thread. Tag it
      // here; otherwise the fallback rejects whichever send is mounted now, and
      // an older create failure rejects a newer send (#8092 review).
      if (typeof requested === "string") {
        markRunError(error, requested);
      }
      throw error;
    }
  };
  taggedClients.add(client);
  return client;
}
