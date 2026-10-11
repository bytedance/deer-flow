import { afterEach, expect, it, rs } from "@rstest/core";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";

import type { LoadedContribution } from "@/core/extensions/registry";
import { useExtensionMentions } from "@/core/extensions/use-mentions";

let viewer = "alice";
let locale = "en-US";
let discoveryPending = false;
let discoveryError = false;
const search = rs.fn();
const initialEntries: LoadedContribution[] = [
  {
    namespace: "test.team",
    viewer_id: viewer,
    module: "team",
    entry: null,
    title: "Team",
    description: "",
    settings: { enabled: true },
    extension: {
      apiVersion: 1,
      module: "team",
      mentionProviders: [{ id: "members", label: "Members", search }],
    },
  },
];
let entries = initialEntries;
rs.mock("@/core/auth/AuthProvider", () => ({
  useAuth: () => ({ user: { id: viewer } }),
}));
rs.mock("@/core/i18n/hooks", () => ({ useI18n: () => ({ locale }) }));
rs.mock("@/core/extensions/hooks", () => ({
  useFrontendExtensions: () => ({
    data: entries,
    isPending: discoveryPending,
    isError: discoveryError,
  }),
}));
afterEach(() => {
  cleanup();
  search.mockReset();
  viewer = "alice";
  locale = "en-US";
  discoveryPending = false;
  discoveryError = false;
  entries = initialEntries;
  rs.restoreAllMocks();
});

it.each([
  "empty",
  "backend-only",
  "no contribution",
  "empty providers",
  "disabled",
  "other viewer",
])("settles immediately without a search timer for %s", (scenario) => {
  const entry = initialEntries[0]!;
  if (scenario === "empty") entries = [];
  if (scenario === "backend-only")
    entries = [{ ...entry, module: null, extension: undefined }];
  if (scenario === "no contribution")
    entries = [{ ...entry, extension: { apiVersion: 1, module: "team" } }];
  if (scenario === "empty providers")
    entries = [
      {
        ...entry,
        extension: { apiVersion: 1, module: "team", mentionProviders: [] },
      },
    ];
  if (scenario === "disabled")
    entries = [{ ...entry, settings: { enabled: false } }];
  if (scenario === "other viewer") entries = [{ ...entry, viewer_id: "bob" }];
  const timer = rs.spyOn(globalThis, "setTimeout");
  const { result, rerender } = renderHook(
    ({ query }) => useExtensionMentions(query, "thread"),
    { initialProps: { query: "a" } },
  );
  expect(result.current.items).toEqual([]);
  expect(result.current.loading).toBe(false);
  expect(result.current.failed).toBe(false);
  rerender({ query: "al" });
  expect(result.current.loading).toBe(false);
  expect(timer.mock.calls.some(([, delay]) => delay === 150)).toBe(false);
  expect(search).not.toHaveBeenCalled();
});

it("keeps discovery loading and failure states when no providers are known", () => {
  entries = [];
  discoveryPending = true;
  const { result, rerender } = renderHook(() =>
    useExtensionMentions("a", "thread"),
  );
  expect(result.current.loading).toBe(true);
  discoveryPending = false;
  discoveryError = true;
  rerender();
  expect(result.current.loading).toBe(false);
  expect(result.current.failed).toBe(true);
});

it("clears a removed provider immediately and ignores its late response", async () => {
  let release!: (value: { id: string; label: string }[]) => void;
  search.mockImplementation(
    () =>
      new Promise((resolve) => {
        release = resolve;
      }),
  );
  const { result, rerender } = renderHook(() =>
    useExtensionMentions("a", "thread"),
  );
  expect(result.current.loading).toBe(true);
  await waitFor(() => expect(search).toHaveBeenCalledTimes(1));
  entries = [];
  rerender();
  expect(result.current.loading).toBe(false);
  expect(result.current.items).toEqual([]);
  await act(async () => release([{ id: "late", label: "Late" }]));
  expect(result.current.items).toEqual([]);
});

it("retains settled candidates during a query refresh without a picker-wide loading flash", async () => {
  let release!: (value: { id: string; label: string }[]) => void;
  search.mockResolvedValueOnce([{ id: "old", label: "Alice" }]);
  search.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        release = resolve;
      }),
  );
  const { result, rerender } = renderHook(
    ({ query }) => useExtensionMentions(query, "thread"),
    { initialProps: { query: "a" } },
  );
  await waitFor(() => expect(result.current.items[0]?.id).toBe("old"));
  rerender({ query: "al" });
  expect(result.current.items[0]?.id).toBe("old");
  expect(result.current.loading).toBe(false);
  await waitFor(() => expect(search).toHaveBeenCalledTimes(2));
  expect(result.current.items[0]?.id).toBe("old");
  await act(async () => {
    release([{ id: "new", label: "Alison" }]);
  });
  expect(result.current.items[0]?.id).toBe("new");
});

it.each(["viewer", "thread", "locale", "entries"])(
  "clears settled candidates immediately when %s changes",
  async (change) => {
    search.mockResolvedValueOnce([{ id: "old", label: "Alice" }]);
    search.mockImplementation(() => new Promise(() => undefined));
    const { result, rerender } = renderHook(
      ({ threadId }) => useExtensionMentions("a", threadId),
      { initialProps: { threadId: "one" } },
    );
    await waitFor(() => expect(result.current.items[0]?.id).toBe("old"));
    if (change === "viewer") viewer = "bob";
    if (change === "locale") locale = "zh-CN";
    if (change === "entries") entries = [...entries];
    rerender({ threadId: change === "thread" ? "two" : "one" });
    expect(result.current.items).toEqual([]);
    expect(result.current.loading).toBe(change !== "viewer");
  },
);

it("does not replace fresh same-context results with a late superseded query", async () => {
  let release!: (value: { id: string; label: string }[]) => void;
  search.mockResolvedValueOnce([{ id: "first", label: "First" }]);
  search.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        release = resolve;
      }),
  );
  search.mockResolvedValueOnce([{ id: "latest", label: "Latest" }]);
  const { result, rerender } = renderHook(
    ({ query }) => useExtensionMentions(query, "thread"),
    { initialProps: { query: "first" } },
  );
  await waitFor(() => expect(result.current.items[0]?.id).toBe("first"));
  rerender({ query: "slow" });
  await waitFor(() => expect(search).toHaveBeenCalledTimes(2));
  rerender({ query: "latest" });
  await waitFor(() => expect(result.current.items[0]?.id).toBe("latest"));
  await act(async () => {
    release([{ id: "stale", label: "Stale" }]);
  });
  expect(result.current.items[0]?.id).toBe("latest");
});
it("cancels old queries and fences results across query, thread, viewer and unmount", async () => {
  let release!: (value: { id: string; label: string }[]) => void;
  let signal!: AbortSignal;
  search.mockImplementationOnce((_query, context) => {
    signal = context.signal;
    return new Promise((resolve) => {
      release = resolve;
    });
  });
  search.mockResolvedValue([{ id: "new", label: "Current" }]);
  const { result, rerender, unmount } = renderHook(
    ({ query, threadId }) => useExtensionMentions(query, threadId),
    { initialProps: { query: "old", threadId: "one" } },
  );
  await waitFor(() => expect(search).toHaveBeenCalledTimes(1));
  rerender({ query: "new", threadId: "two" });
  expect(signal.aborted).toBe(true);
  await waitFor(() => expect(result.current.items[0]?.id).toBe("new"));
  await act(async () => {
    release([{ id: "old", label: "Stale" }]);
  });
  expect(result.current.items[0]?.id).toBe("new");
  viewer = "bob";
  rerender({ query: "new", threadId: "two" });
  expect(result.current.items).toEqual([]);
  await waitFor(() => expect(result.current.loading).toBe(false));
  expect(result.current.items).toEqual([]);
  entries = entries.map((entry) => ({ ...entry, viewer_id: viewer }));
  rerender({ query: "last", threadId: "three" });
  await waitFor(() => expect(search).toHaveBeenCalledTimes(3));
  unmount();
  expect(search.mock.calls[2]![1].signal.aborted).toBe(true);
});
