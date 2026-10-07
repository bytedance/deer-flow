import {
  afterEach,
  beforeEach,
  describe,
  expect,
  rs,
  test,
} from "@rstest/core";
import { QueryClient, QueryObserver } from "@tanstack/react-query";

const mocks = rs.hoisted(() => ({ fetch: rs.fn() }));
rs.mock("@/core/api/fetcher", () => ({ fetch: mocks.fetch }));
rs.mock("@/core/config", () => ({ getBackendBaseURL: () => "" }));

import {
  applyThreadActivity,
  pollThreadActivity,
  THREAD_ACTIVITY_POLL_MS,
  THREAD_ACTIVITY_QUERY_KEY,
  threadActivityQueryOptions,
  threadActivityState,
  type ThreadActivityResponse,
} from "@/core/threads/activity";
import { INFINITE_THREADS_QUERY_KEY_PREFIX } from "@/core/threads/hooks";

const clients: QueryClient[] = [];

function client() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  clients.push(queryClient);
  return queryClient;
}

function response(
  overrides: Partial<ThreadActivityResponse> = {},
): ThreadActivityResponse {
  return {
    cursor: "10:run-10",
    threads: [],
    truncated: false,
    read_version: 0,
    ...overrides,
  };
}

/** Query keys passed to `invalidateQueries`, in order. */
function spyInvalidations(queryClient: QueryClient) {
  const keys: unknown[] = [];
  const original = queryClient.invalidateQueries.bind(queryClient);
  queryClient.invalidateQueries = ((filters?: { queryKey?: unknown }) => {
    keys.push(filters?.queryKey);
    return original(filters as Parameters<typeof original>[0]);
  }) as typeof queryClient.invalidateQueries;
  return keys;
}

/** A client past its seeding response, with its later invalidations recorded. */
function seededClient(readVersion = 0) {
  const queryClient = client();
  applyThreadActivity(
    queryClient,
    threadActivityState(queryClient),
    response({ read_version: readVersion }),
  );
  return { queryClient, keys: spyInvalidations(queryClient) };
}

/** Apply one poll response to the client's own activity state. */
function apply(
  queryClient: QueryClient,
  overrides: Partial<ThreadActivityResponse>,
) {
  return applyThreadActivity(
    queryClient,
    threadActivityState(queryClient),
    response(overrides),
  );
}

/** Both thread lists, in the order a change invalidates them. */
const LIST_KEYS = [["threads", "search"], INFINITE_THREADS_QUERY_KEY_PREFIX];

beforeEach(() => {
  mocks.fetch.mockReset();
});
afterEach(() => {
  clients.splice(0).forEach((queryClient) => queryClient.clear());
});

describe("activity responses", () => {
  test("the first response seeds the cursor and refreshes the lists once", () => {
    const queryClient = client();
    const keys = spyInvalidations(queryClient);
    const state = threadActivityState(queryClient);
    const outcome = applyThreadActivity(
      queryClient,
      state,
      response({
        threads: [
          { thread_id: "t-1", origin_kind: "schedule", status: "success" },
        ],
        read_version: 4,
      }),
    );
    // The lists may predate a run the seed already counts: later polls start
    // after it, so only this refresh can show that thread.
    expect(outcome).toEqual({
      seeded: true,
      threads: true,
      scheduledTasks: false,
    });
    expect(keys).toEqual(LIST_KEYS);
    expect(state).toEqual({ cursor: "10:run-10", readVersion: 4 });
  });

  test("a server-originated thread invalidates both thread lists", () => {
    const { queryClient, keys } = seededClient();
    const outcome = apply(queryClient, {
      cursor: "12:run-12",
      threads: [
        { thread_id: "t-1", origin_kind: "im_channel", status: "success" },
      ],
    });
    expect(outcome.threads).toBe(true);
    expect(outcome.scheduledTasks).toBe(false);
    expect(keys).toEqual(LIST_KEYS);
    expect(threadActivityState(queryClient).cursor).toBe("12:run-12");
  });

  test("a scheduled thread also refreshes the scheduled-task queries", () => {
    const { queryClient, keys } = seededClient();
    apply(queryClient, {
      threads: [
        { thread_id: "t-1", origin_kind: "schedule", status: "running" },
      ],
    });
    expect(keys).toContainEqual(["scheduled-tasks"]);
    expect(keys).toContainEqual(["threads", "search"]);
  });

  test("a higher read_version alone (a read on another device) invalidates the lists", () => {
    const { queryClient, keys } = seededClient(3);
    const outcome = apply(queryClient, { read_version: 4 });
    expect(outcome.threads).toBe(true);
    expect(keys).toEqual(LIST_KEYS);
    expect(threadActivityState(queryClient).readVersion).toBe(4);
  });

  test("a truncated page invalidates even without listed threads", () => {
    const { queryClient, keys } = seededClient();
    apply(queryClient, { truncated: true });
    expect(keys).toHaveLength(2);
  });

  test("an idle poll, interactive rows and an older read_version change nothing", () => {
    const { queryClient, keys } = seededClient(5);
    const state = threadActivityState(queryClient);
    applyThreadActivity(queryClient, state, response({ read_version: 5 }));
    applyThreadActivity(
      queryClient,
      state,
      response({
        threads: [{ thread_id: "t-1", origin_kind: null, status: "success" }],
        read_version: 5,
      }),
    );
    // Computed before this tab's own read raised the clock: not a change.
    applyThreadActivity(queryClient, state, response({ read_version: 4 }));
    expect(keys).toEqual([]);
    expect(state.readVersion).toBe(5);
  });
});

describe("polling", () => {
  test("seeds without a cursor, then polls from the stored cursor", async () => {
    const queryClient = client();
    mocks.fetch
      .mockResolvedValueOnce(Response.json(response({ cursor: "7:run-a" })))
      .mockResolvedValueOnce(Response.json(response({ cursor: "9:run-b" })));
    await pollThreadActivity(queryClient);
    await pollThreadActivity(queryClient);
    const urls = mocks.fetch.mock.calls.map(([url]) => String(url));
    expect(urls[0]).toBe("/api/thread-activity?limit=200");
    expect(new URL(urls[1]!, "http://x").searchParams.get("cursor")).toBe(
      "7:run-a",
    );
    expect(threadActivityState(queryClient).cursor).toBe("9:run-b");
  });

  test("an invalid cursor re-seeds and refetches the lists once", async () => {
    const { queryClient, keys } = seededClient();
    mocks.fetch
      .mockResolvedValueOnce(
        Response.json(
          { detail: { code: "invalid_cursor", message: "Invalid" } },
          { status: 422 },
        ),
      )
      .mockResolvedValueOnce(Response.json(response({ cursor: "1:run-z" })));
    await pollThreadActivity(queryClient);
    expect(String(mocks.fetch.mock.calls[1]![0])).not.toContain("cursor=");
    expect(threadActivityState(queryClient).cursor).toBe("1:run-z");
    expect(keys).toEqual(LIST_KEYS);
  });

  test("query options poll every 15 s, on focus, and never in the background", () => {
    const options = threadActivityQueryOptions(client(), { enabled: true });
    expect(options.queryKey).toEqual(THREAD_ACTIVITY_QUERY_KEY);
    expect(options.queryKey).toEqual(["threads", "activity"]);
    expect(options.refetchInterval).toBe(THREAD_ACTIVITY_POLL_MS);
    expect(THREAD_ACTIVITY_POLL_MS).toBe(15_000);
    expect(options.refetchIntervalInBackground).toBe(false);
    expect(options.refetchOnWindowFocus).toBe(true);
  });

  test("nothing is requested when the feature is unavailable", async () => {
    const queryClient = client();
    const observer = new QueryObserver(
      queryClient,
      threadActivityQueryOptions(queryClient, { enabled: false }),
    );
    const unsubscribe = observer.subscribe(() => undefined);
    await new Promise((resolve) => setTimeout(resolve, 0));
    unsubscribe();
    expect(mocks.fetch).not.toHaveBeenCalled();
  });
});
