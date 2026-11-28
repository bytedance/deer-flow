/**
 * Errors thrown by a run request. The SDK reports them through the stream's
 * `onError` without run metadata, exactly like a failed history fetch, so the
 * thread the request was sent to is the only identity the hook can settle the
 * refusal with. It is recorded here, at the call that knows it.
 */
const runErrors = new WeakMap<object, string>();

/** Clients already wrapped, so a re-render cannot stack wrappers. */
const taggedClients = new WeakSet<object>();

export function markRunError(error: unknown, threadId: string): void {
  if (typeof error === "object" && error !== null) {
    runErrors.set(error, threadId);
  }
}

/** The thread a refused run request was sent to, when it came from the SDK. */
export function runErrorThreadId(error: unknown): string | undefined {
  return typeof error === "object" && error !== null
    ? runErrors.get(error)
    : undefined;
}

/**
 * `RunsClient.stream` is an overloaded async generator whose first argument is
 * the thread, so the wrapper reads it loosely and hands the call straight back.
 */
type LooseRunStream = (
  ...args: unknown[]
) => AsyncGenerator<unknown, void, unknown>;
type RunClient = { runs: { stream: unknown } };

/**
 * Tag errors thrown while a run request streams so `onError` can settle the
 * send that produced them.
 *
 * A refusal rejects on the first iteration, not at the call, so the wrapper
 * wraps the iteration itself and rethrows the same error to keep its identity
 * for the stream's `onError`.
 */
export function withRunErrorTagging<T extends RunClient>(client: T): T {
  const runs = client.runs as { stream: LooseRunStream } | undefined;
  // Test doubles and non-SDK clients may not expose a run reader; leave them
  // untouched so `onError` falls back to the mounted send.
  if (!runs || typeof runs.stream !== "function" || taggedClients.has(client)) {
    return client;
  }
  const stream = runs.stream.bind(runs);
  runs.stream = async function* (
    ...args: unknown[]
  ): AsyncGenerator<unknown, void, unknown> {
    const threadId = typeof args[0] === "string" ? args[0] : undefined;
    try {
      yield* stream(...args);
    } catch (error) {
      if (threadId) {
        markRunError(error, threadId);
      }
      throw error;
    }
  };
  taggedClients.add(client);
  return client;
}
