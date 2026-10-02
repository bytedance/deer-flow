import { afterEach, expect, it, rs } from "@rstest/core";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";

import { useExtensionMentions } from "@/core/extensions/use-mentions";

let viewer = "alice";
let locale = "en-US";
const search = rs.fn();
const initialEntries = [
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
    isPending: false,
    isError: false,
  }),
}));
afterEach(() => {
  cleanup();
  search.mockReset();
  viewer = "alice";
  locale = "en-US";
  entries = initialEntries;
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
    expect(result.current.loading).toBe(true);
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
